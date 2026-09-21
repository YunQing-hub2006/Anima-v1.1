"""供自动发现测试使用的示例插件与工厂函数。"""

from __future__ import annotations

from anima.core import Context, Plugin


class FakePlugin(Plugin):
    """entry point 指向类时的形态。"""

    name = "fake"

    async def load(self, ctx: Context) -> None:
        ...


def make_fake_plugin() -> Plugin:
    """entry point 指向无参工厂函数时的形态。"""
    return FakePlugin()


class NotAPlugin:
    """故意不是 Plugin，用于验证发现器的防御分支。"""
