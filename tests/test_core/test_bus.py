"""Phase 2 - bus.py 测试。"""

from __future__ import annotations

import asyncio

from anima.core.bus import EventBus


def _boom_hook(event, handler, exc) -> None:
    """上报钩子自身抛异常——用于验证异常隔离不被钩子打破。"""
    raise RuntimeError("钩子也崩了")


def test_subscribe_emit(bus: EventBus):
    """精确事件订阅与发布。"""
    received: list = []
    bus.subscribe("user.click", lambda d: received.append(d))
    bus.emit("user.click", {"x": 1})
    assert received == [{"x": 1}]


def test_unsubscribe(bus: EventBus):
    """取消订阅后不再收到事件。"""
    received: list = []
    handler = lambda d: received.append(d)  # noqa: E731
    bus.subscribe("evt", handler)
    bus.unsubscribe("evt", handler)
    bus.emit("evt", 1)
    assert received == []


def test_unsubscribe_idempotent(bus: EventBus):
    """重复 unsubscribe 不抛异常。"""
    handler = lambda d: None  # noqa: E731
    bus.unsubscribe("never-subscribed", handler)  # 不存在 -> 静默
    bus.subscribe("evt", handler)
    bus.unsubscribe("evt", handler)
    bus.unsubscribe("evt", handler)  # 第二次 -> 静默
    assert bus.count() == 0


def test_wildcard_match(bus: EventBus):
    """'*' 匹配一切；'user.*' 匹配 'user.click' 不匹配 'user'。"""
    all_events: list = []
    user_events: list = []
    bus.subscribe("*", lambda d: all_events.append(d))
    bus.subscribe("user.*", lambda d: user_events.append(d))

    bus.emit("user.click", 1)
    bus.emit("user.login", 2)
    bus.emit("user", 3)
    bus.emit("system.boot", 4)

    assert all_events == [1, 2, 3, 4]
    assert user_events == [1, 2]  # 不含裸 "user"，也不含其他前缀


def test_wildcard_unsubscribe(bus: EventBus):
    """通配订阅也能取消。"""
    received: list = []
    handler = lambda d: received.append(d)  # noqa: E731
    bus.subscribe("user.*", handler)
    bus.unsubscribe("user.*", handler)
    bus.emit("user.click", 1)
    assert received == []
    assert bus.count() == 0


def test_handler_exception_isolation(bus: EventBus):
    """单个 handler 抛异常不影响其他 handler。"""
    good: list = []

    def bad(_):
        raise RuntimeError("handler 崩了")

    bus.subscribe("evt", bad)
    bus.subscribe("evt", lambda d: good.append(d))
    bus.emit("evt", 42)  # 不向外抛异常
    assert good == [42]


def test_emit_with_no_handlers(bus: EventBus):
    """向无人订阅的事件发布是空操作。"""
    bus.emit("nobody-listens", "data")


def test_multiple_handlers_same_event(bus: EventBus):
    """同一事件的多个 handler 依次执行。"""
    calls: list[str] = []
    bus.subscribe("evt", lambda d: calls.append("a"))
    bus.subscribe("evt", lambda d: calls.append("b"))
    bus.emit("evt", None)
    assert calls == ["a", "b"]
    assert bus.count() == 2


async def test_emit_async():
    """emit_async 对协程 handler 创建 Task，同步 handler 立即执行。"""
    bus = EventBus()
    results: list = []

    async def slow(d):
        await asyncio.sleep(0)
        results.append(("slow", d))

    def fast(d):
        results.append(("fast", d))

    bus.subscribe("evt", slow)
    bus.subscribe("evt", fast)

    tasks = bus.emit_async("evt", 7)
    assert len(tasks) == 1
    await asyncio.gather(*tasks)
    assert ("fast", 7) in results
    assert ("slow", 7) in results


async def test_emit_async_exception_isolation():
    """emit_async 中崩溃的协程 handler 不影响同步 handler。"""
    bus = EventBus()
    seen: list = []

    async def boom(d):
        raise RuntimeError("异步 handler 崩了")

    bus.subscribe("evt", boom)
    bus.subscribe("evt", lambda d: seen.append(d))
    tasks = bus.emit_async("evt", 1)
    await asyncio.gather(*tasks, return_exceptions=True)
    assert seen == [1]


async def test_emit_schedules_coroutine_handler():
    """同步 emit 遇到协程 handler 时调度到运行中的事件循环。"""
    bus = EventBus()
    done = asyncio.Event()

    async def handler(d):
        done.set()

    bus.subscribe("evt", handler)
    bus.emit("evt", None)
    await asyncio.wait_for(done.wait(), timeout=1)


def test_error_hook_receives_handler_exception():
    """on_error 钩子收到 (事件名, handler, 异常)，异常本身仍被隔离。"""
    seen: list = []
    bus = EventBus(on_error=lambda ev, h, exc: seen.append((ev, h, exc)))
    good: list = []

    def bad(_):
        raise RuntimeError("handler 崩了")

    bus.subscribe("evt", bad)
    bus.subscribe("evt", lambda d: good.append(d))
    bus.emit("evt", 42)

    assert good == [42]  # 隔离不变式保持
    assert len(seen) == 1
    assert seen[0][0] == "evt"
    assert seen[0][1] is bad
    assert isinstance(seen[0][2], RuntimeError)


def test_error_hook_covers_emit_async_sync_handler():
    """emit_async 的同步 handler 异常同样经钩子上报。"""
    seen: list = []
    bus = EventBus(on_error=lambda ev, h, exc: seen.append(exc))

    def bad(_):
        raise ValueError("sync boom")

    bus.subscribe("evt", bad)
    assert bus.emit_async("evt", 1) == []
    assert len(seen) == 1
    assert isinstance(seen[0], ValueError)


def test_set_error_hook_replaces_and_clears():
    """set_error_hook 可替换钩子；None 恢复默认（不再回调旧钩子）。"""
    seen: list = []
    bus = EventBus(on_error=lambda ev, h, exc: seen.append("first"))
    bus.set_error_hook(lambda ev, h, exc: seen.append("second"))

    def bad(_):
        raise RuntimeError("boom")

    bus.subscribe("evt", bad)
    bus.emit("evt", None)
    assert seen == ["second"]

    bus.set_error_hook(None)
    bus.emit("evt", None)  # 走默认 logger 上报，不回调旧钩子
    assert seen == ["second"]


def test_error_hook_failure_does_not_escape():
    """钩子自己抛异常也不得从 emit 漏给发布方。"""
    bus = EventBus(on_error=_boom_hook)
    seen: list = []
    bus.subscribe("evt", lambda d: seen.append(d))

    def bad(_):
        raise RuntimeError("handler 崩了")

    bus.subscribe("evt", bad)
    bus.emit("evt", 1)
    assert seen == [1]


async def test_error_hook_failure_does_not_escape_emit_async():
    """emit_async 路径同样不让钩子异常外泄。"""
    bus = EventBus(on_error=_boom_hook)

    def bad(_):
        raise RuntimeError("handler 崩了")

    bus.subscribe("evt", bad)
    assert bus.emit_async("evt", 1) == []


def test_default_error_reporting_uses_anima_logger(caplog):
    """未提供钩子时默认写 anima.bus logger（可观测性默认开启）。"""
    import logging

    bus = EventBus()

    def bad(_):
        raise RuntimeError("handler 崩了")

    bus.subscribe("evt", bad)
    with caplog.at_level(logging.ERROR, logger="anima.bus"):
        bus.emit("evt", None)
    assert any(r.name == "anima.bus" for r in caplog.records)
    assert any("handler 崩了" in (r.exc_text or "") for r in caplog.records)


def test_clear_removes_all(bus: EventBus):
    """clear 清空全部订阅。"""
    bus.subscribe("a", lambda d: None)
    bus.subscribe("b.*", lambda d: None)
    bus.subscribe("*", lambda d: None)
    bus.clear()
    assert bus.count() == 0


def test_unsubscribe_unknown_handler_for_known_event(bus: EventBus):
    """事件存在但 handler 不在列表中：静默成功，不影响其他订阅。"""
    kept = lambda d: None  # noqa: E731
    stranger = lambda d: None  # noqa: E731
    bus.subscribe("evt", kept)
    bus.unsubscribe("evt", stranger)
    assert bus.count() == 1
    bus.unsubscribe("evt", kept)  # 正常取消
    assert bus.count() == 0


async def test_emit_async_sync_handler_exception_isolated():
    """emit_async 中同步 handler 抛异常不影响其他 handler。"""
    bus = EventBus()
    seen: list = []

    def boom(d):
        raise RuntimeError("同步 handler 崩了")

    bus.subscribe("evt", boom)
    bus.subscribe("evt", lambda d: seen.append(d))
    tasks = bus.emit_async("evt", 1)
    assert tasks == []  # 无协程 handler
    assert seen == [1]


def test_emit_coroutine_handler_without_loop():
    """事件循环外同步 emit 协程 handler：协程被丢弃，不抛异常。"""
    bus = EventBus()

    async def handler(d): ...

    bus.subscribe("evt", handler)
    bus.emit("evt", None)  # 无运行中的事件循环 -> 静默


def test_handler_order_contract(bus: EventBus):
    """顺序契约：精确 handler 先于通配 handler，组内按注册顺序。"""
    calls: list[str] = []
    bus.subscribe("evt.click", lambda d: calls.append("exact-1"))
    bus.subscribe("evt.*", lambda d: calls.append("wild-1"))
    bus.subscribe("evt.click", lambda d: calls.append("exact-2"))
    bus.subscribe("*", lambda d: calls.append("wild-2"))
    bus.subscribe("evt.*", lambda d: calls.append("wild-3"))

    bus.emit("evt.click", None)

    assert calls == ["exact-1", "exact-2", "wild-1", "wild-2", "wild-3"]
