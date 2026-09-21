"""事件总线：支持精确事件名与 ``前缀.*`` 通配符的发布订阅系统。

匹配规则:

- 精确订阅 ``"user.click"`` 只收到同名事件。
- 通配订阅 ``"user.*"`` 收到所有以 ``"user."`` 开头的事件，
  但不匹配裸事件名 ``"user"``。
- 通配订阅 ``"*"`` 收到一切事件。

执行顺序契约（v1.1.1 明确）: 精确订阅的 handler 先于通配 handler 执行，
两组各自内部按注册顺序执行；同步 handler 立即执行，协程 handler 的
执行时机由事件循环调度决定，与注册顺序无关。

单个 handler 抛异常不影响其他 handler 的执行：异常被隔离、交由
``on_error`` 钩子上报（默认写 ``anima.bus`` logger），不上抛给发布方。

线程语义（v1.1 明确）:

- 总线内部是普通 dict / list，无锁、无 await 临界区；单个 ``emit``
  调用是原子的（纯同步代码，不会中途让出）。
- 因此「从任意线程同步调用 ``emit`` / ``subscribe`` / ``unsubscribe``」
  是安全的：handler 在**调用方线程**立即执行。
- 跨线程协程 handler 不会被 ``emit`` 调度（调度依赖运行中的事件循环，
  即 ``asyncio.get_running_loop`` 是线程局部的）。
- 危险模式是「多线程并发 subscribe 同一事件」造成的 list 竞争--框架
  层约定：订阅只发生在插件 load/unload（内核线程），UI 线程只 emit。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from anima.core.log import logger

Handler = Callable[[Any], Any]

#: handler 异常上报钩子，签名 ``(event, handler, exc) -> None``。
#:
#: 上报**不改变异常隔离语义**：异常依旧不会抛给 ``emit`` 的调用方，
#: 只是不再无声无息。
ErrorHook = Callable[[str, Handler, BaseException], None]

_log = logger.getChild("bus")

__all__ = ["ErrorHook", "EventBus"]


def _wildcard_prefix(pattern: str) -> str:
    """把 ``"user.*"`` 转换为前缀 ``"user."``（调用方已保证格式合法）。"""
    return pattern[:-1]


class EventBus:
    """进程内同步事件总线。

    精确事件走 ``dict`` 索引实现 O(1) 查找；通配订阅维护在独立的
    ``(前缀, handler)`` 列表中，emit 时线性扫描。

    单个 handler 抛出的异常被**隔离**（不上抛给发布方）并交给
    ``on_error`` 上报；未提供钩子时默认写 ``anima.bus`` logger。
    因此"订阅写错了"不会再完全无声。
    """

    def __init__(self, on_error: ErrorHook | None = None) -> None:
        self._exact: dict[str, list[Handler]] = {}
        self._wild: list[tuple[str, Handler]] = []
        self._on_error = on_error

    def set_error_hook(self, hook: ErrorHook | None) -> None:
        """替换（或清除）handler 异常上报钩子；``None`` 恢复默认 logger 上报。"""
        self._on_error = hook

    def _report(self, event: str, handler: Handler, exc: BaseException) -> None:
        """上报被隔离的 handler 异常。

        上报本身也必须遵守异常隔离不变式：钩子自己抛异常时退回默认
        logger，绝不让异常从 ``emit`` 漏给发布方。
        """
        try:
            if self._on_error is not None:
                self._on_error(event, handler, exc)
            else:
                _log.error("事件 handler 抛异常: event=%r handler=%r", event, handler, exc_info=exc)
        except Exception:
            _log.exception("异常上报钩子自身失败: event=%r", event)

    # -- 订阅管理 ---------------------------------------------------------

    def subscribe(self, event: str, handler: Handler) -> None:
        """订阅事件。``event`` 为 ``"*"`` 或 ``"前缀.*"`` 时按通配处理。"""
        if event == "*":
            self._wild.append(("", handler))
            return
        if event.endswith(".*") and len(event) >= 2:
            self._wild.append((_wildcard_prefix(event), handler))
            return
        self._exact.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        """取消订阅；订阅不存在时静默成功（幂等）。"""
        if event == "*" or (event.endswith(".*") and len(event) >= 2):
            prefix = "" if event == "*" else _wildcard_prefix(event)
            self._wild = [(p, h) for p, h in self._wild if not (p == prefix and h == handler)]
            return
        handlers = self._exact.get(event)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass
        if not handlers:
            del self._exact[event]

    def count(self) -> int:
        """当前有效订阅总数（精确 + 通配）。"""
        return sum(len(v) for v in self._exact.values()) + len(self._wild)

    # -- 发布 ---------------------------------------------------------

    def _wild_matches(self, event: str) -> list[Handler]:
        matched = [h for prefix, h in self._wild if event.startswith(prefix)]
        return matched

    def emit(self, event: str, data: Any = None) -> None:
        """同步发布事件。

        同步 handler 立即执行；协程 handler 调度到事件循环（无运行中的
        事件循环时静默丢弃并保持异常隔离）。单个 handler 的异常被隔离
        并经 ``_report`` 上报，不影响其他 handler。
        """
        for handler in self._handlers(event):
            try:
                result = handler(data)
            except Exception as exc:
                self._report(event, handler, exc)
                continue
            if asyncio.iscoroutine(result):
                _schedule_coroutine(result)

    def emit_async(self, event: str, data: Any = None) -> list[asyncio.Task[None]]:
        """异步发布事件。

        协程 handler 各自包装为 Task 立即返回；同步 handler 同步执行。
        返回创建的 Task 列表（无协程 handler 时为空列表）。同步 handler
        的异常同 :meth:`emit`：隔离并上报，不上抛。
        """
        tasks: list[asyncio.Task[None]] = []
        for handler in self._handlers(event):
            try:
                result = handler(data)
            except Exception as exc:
                self._report(event, handler, exc)
                continue
            if asyncio.iscoroutine(result):
                tasks.append(asyncio.ensure_future(result))
        return tasks

    def _handlers(self, event: str) -> list[Handler]:
        exact = self._exact.get(event, [])
        wild = self._wild_matches(event)
        return [*exact, *wild]

    def clear(self) -> None:
        """移除全部订阅（框架 stop 时调用）。"""
        self._exact.clear()
        self._wild.clear()


def _schedule_coroutine(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    loop.create_task(coro)
