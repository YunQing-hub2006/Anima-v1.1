"""副作用追踪器：插件卸载时自动、完整、异常安全地回滚全部副作用。"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from anima.core.exceptions import RollbackError

if TYPE_CHECKING:
    from anima.core.bus import EventBus
    from anima.core.registry import ServiceRegistry

CleanupFn = Callable[[], None] | Callable[[], Awaitable[None]]

__all__ = ["EffectTracker", "CleanupFn"]


class EffectTracker:
    """以 LIFO 栈记录回滚操作，插件卸载时逆序执行。

    单个 cleanup 失败不会中断后续回滚；所有异常收集完毕后统一以
    :class:`RollbackError` 抛出。
    """

    def __init__(self) -> None:
        self._stack: list[CleanupFn] = []

    def push(self, rollback: CleanupFn) -> None:
        """压入一个回滚操作；同一函数重复压入会被记录多次。"""
        self._stack.append(rollback)

    def on(self, target: "EventBus", event: str, handler: Callable[[Any], Any]) -> None:
        """订阅事件并自动记录对应的取消订阅。"""
        target.subscribe(event, handler)
        self.push(lambda: target.unsubscribe(event, handler))

    def provide(self, registry: "ServiceRegistry", name: str, instance: Any) -> None:
        """注册服务并自动记录对应的注销。"""
        registry.register(name, instance)
        self.push(lambda: registry.unregister(name))

    async def rollback(self) -> None:
        """逆序执行全部回滚操作并清空栈。

        有失败项时抛 :class:`RollbackError`（其 ``errors`` 属性是全部
        子异常列表）；栈为空时静默返回。
        """
        errors: list[BaseException] = []
        while self._stack:
            cleanup = self._stack.pop()
            try:
                result = cleanup()
            except Exception as exc:
                errors.append(exc)
                continue
            if inspect.isawaitable(result):
                try:
                    await result
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise RollbackError(errors)

    def count(self) -> int:
        """尚未回滚的副作用数量。"""
        return len(self._stack)

    def clear(self) -> None:
        """清空栈但不执行任何回滚操作。"""
        self._stack.clear()
