"""Phase 2 - effects.py 测试。"""

from __future__ import annotations

import pytest

from anima.core.bus import EventBus
from anima.core.effects import EffectTracker
from anima.core.exceptions import RollbackError
from anima.core.registry import ServiceRegistry


async def test_push_rollback_lifo():
    """push + rollback 成对清除，LIFO 顺序正确。"""
    tracker = EffectTracker()
    order: list[str] = []
    tracker.push(lambda: order.append("first"))
    tracker.push(lambda: order.append("second"))
    tracker.push(lambda: order.append("third"))

    assert tracker.count() == 3
    await tracker.rollback()
    assert order == ["third", "second", "first"]
    assert tracker.count() == 0


async def test_rollback_exception_survival():
    """中间 cleanup 失败不中断后续回滚，最后统一抛 RollbackError。"""
    tracker = EffectTracker()
    executed: list[str] = []

    def failing():
        raise RuntimeError("中间失败")

    tracker.push(lambda: executed.append("first"))
    tracker.push(failing)
    tracker.push(lambda: executed.append("last"))

    with pytest.raises(RollbackError):
        await tracker.rollback()

    # 失败项之前和之后的 cleanup 都执行了
    assert executed == ["last", "first"]


async def test_rollback_empty():
    """空 tracker rollback 不抛异常。"""
    tracker = EffectTracker()
    await tracker.rollback()


async def test_rollback_error_aggregation():
    """多个失败被聚合成一个 RollbackError。"""
    tracker = EffectTracker()

    def boom(tag: str):
        def inner():
            raise ValueError(tag)

        return inner

    tracker.push(boom("a"))
    tracker.push(boom("b"))
    tracker.push(boom("c"))

    with pytest.raises(RollbackError) as info:
        await tracker.rollback()

    assert len(info.value.errors) == 3
    assert [str(e) for e in info.value.errors] == ["c", "b", "a"]


def test_on_auto_unsubscribe():
    """on() 立即生效：订阅后马上能收到事件。"""
    tracker = EffectTracker()
    bus = EventBus()
    received: list = []
    handler = lambda d: received.append(d)  # noqa: E731

    tracker.on(bus, "tick", handler)
    assert tracker.count() == 1
    bus.emit("tick", 1)
    assert received == [1]


async def test_on_auto_unsubscribe_on_rollback():
    """rollback 后 on() 登记的订阅被自动取消。"""
    tracker = EffectTracker()
    bus = EventBus()
    received: list = []
    handler = lambda d: received.append(d)  # noqa: E731

    tracker.on(bus, "tick", handler)
    await tracker.rollback()
    bus.emit("tick", 99)
    assert received == []
    assert bus.count() == 0


async def test_provide_auto_unregister():
    """provide() 注册服务，rollback 自动注销。"""
    tracker = EffectTracker()
    registry = ServiceRegistry()

    tracker.provide(registry, "db", object())
    assert registry.has("db")
    await tracker.rollback()
    assert not registry.has("db")
    assert registry.list() == []


async def test_mixed_sync_async_cleanup():
    """同步与异步 cleanup 混合执行。"""
    tracker = EffectTracker()
    order: list[str] = []

    async def async_cleanup():
        order.append("async")

    tracker.push(lambda: order.append("sync-1"))
    tracker.push(async_cleanup)
    tracker.push(lambda: order.append("sync-2"))

    await tracker.rollback()
    assert order == ["sync-2", "async", "sync-1"]


async def test_async_cleanup_failure_collected():
    """异步 cleanup 抛异常也被收集。"""
    tracker = EffectTracker()

    async def boom():
        raise RuntimeError("异步失败")

    tracker.push(boom)
    with pytest.raises(RollbackError) as info:
        await tracker.rollback()
    assert len(info.value.errors) == 1


async def test_clear():
    """clear 清空栈但不执行任何 cleanup。"""
    tracker = EffectTracker()
    executed: list = []
    tracker.push(lambda: executed.append("x"))
    tracker.clear()
    assert tracker.count() == 0
    await tracker.rollback()  # 空回滚，不执行、不抛异常
    assert executed == []


def test_count():
    """count 反映栈内数量。"""
    tracker = EffectTracker()
    assert tracker.count() == 0
    tracker.push(lambda: None)
    tracker.push(lambda: None)
    assert tracker.count() == 2
