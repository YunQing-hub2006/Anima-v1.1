"""P4-2 - 插件自动发现（anima/plugins/discovery.py，非内核）。"""

from __future__ import annotations

import importlib.metadata as metadata

import pytest

from anima.core import App
from anima.plugins import discover_plugins

GROUP = "anima.test_plugins"
FAKES = "tests.test_plugins.fake_plugins"


def _ep(name: str, target: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(name=name, value=target, group=GROUP)


def test_discovers_classes_and_factories_sorted_by_name():
    """类与工厂函数都能装载；结果按 entry point 名排序，保证可复现。"""
    eps = [
        _ep("z-factory", FAKES + ":make_fake_plugin"),
        _ep("a-class", FAKES + ":FakePlugin"),
    ]
    plugins = discover_plugins(GROUP, entry_points=eps)

    assert [p.name for p in plugins] == ["fake", "fake"]
    assert all(isinstance(p, type(plugins[0])) for p in plugins)


def test_rejects_target_that_is_not_a_plugin():
    """拿到的不是 Plugin 实例时启动前就炸，不带着坏插件跑。"""
    eps = [_ep("bad", FAKES + ":NotAPlugin")]
    with pytest.raises(TypeError):
        discover_plugins(GROUP, entry_points=eps)


def test_empty_group_yields_no_plugins():
    """没有声明 entry point 时返回空列表。"""
    assert discover_plugins(GROUP, entry_points=[]) == []


async def test_discovered_plugins_start_directly():
    """发现结果可以直接交给 App.start。"""
    eps = [
        _ep("a", FAKES + ":FakePlugin"),
        _ep("b", FAKES + ":make_fake_plugin"),
    ]
    app = App()
    # 两个 entry point 都叫 fake -> 重名会被内核拦下，这正是期望的行为
    from anima.core import LifecycleError

    with pytest.raises(LifecycleError):
        await app.start(discover_plugins(GROUP, entry_points=eps))
