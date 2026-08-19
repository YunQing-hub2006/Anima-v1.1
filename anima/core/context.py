"""插件上下文：插件与内核交互的唯一入口，链式 API + 自动副作用追踪。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Self

from anima.core.effects import CleanupFn

if TYPE_CHECKING:
    from anima.core.app import App
    from anima.core.bus import Handler
    from anima.core.plugin import Plugin

__all__ = ["Context"]


class Context:
    """每个插件在 ``load()`` 时独享一个 Context。

    所有方法返回 ``self`` 以支持链式调用。通过 ``on()`` / ``provide()``
    产生的订阅与注册都会被 :class:`EffectTracker` 记录，插件卸载时自动
    回滚；``config`` 是该插件在 ``app.config["plugins"]`` 下的私有切片。
    """

    app: "App"
    plugin: "Plugin"
    effects: "anima.core.effects.EffectTracker"
    config: dict[str, Any]

    def __init__(self, app: "App", plugin: "Plugin") -> None:
        self.app = app
        self.plugin = plugin
        self.effects = app.effects_for(plugin.name)
        plugins_cfg = app.config.setdefault("plugins", {})
        section = plugins_cfg.get(plugin.name)
        if not isinstance(section, dict):
            section = {}
            plugins_cfg[plugin.name] = section
        self.config = section

    def on(self, event: str, handler: "Handler") -> Self:
        """订阅事件；卸载时自动取消订阅。"""
        self.effects.on(self.app.bus, event, handler)
        return self

    def emit(self, event: str, data: Any = None) -> Self:
        """向总线发布事件。"""
        self.app.bus.emit(event, data)
        return self

    def provide(self, name: str, instance: Any) -> Self:
        """注册服务；卸载时自动注销。"""
        self.effects.provide(self.app.registry, name, instance)
        return self

    def use(self, name: str, default: Any = None) -> Any:
        """获取其他插件提供的服务；不存在时返回 ``default``。"""
        return self.app.registry.use(name, default)

    def on_cleanup(self, callback: CleanupFn) -> Self:
        """登记自定义清理操作，插件卸载时逆序执行。"""
        self.effects.push(callback)
        return self
