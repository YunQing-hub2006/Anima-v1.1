# Anima 内核 API 参考（v1.0，已冻结）

> 所有接口位于 `anima.core`，通过 `from anima.core import ...` 使用。
> 本文档为接口冻结版；任何公共接口变更需走评审流程。

## 异常体系 — `exceptions.py`

```python
class AnimaError(Exception)
class DependencyError(AnimaError)        # 缺失/循环依赖
class ServiceExistsError(AnimaError)     # 重复注册同名服务
class ServiceNotFoundError(AnimaError)   # 预留：严格模式获取
class RollbackError(AnimaError)          # 副作用回滚聚合失败
class LifecycleError(AnimaError)         # 状态机违规 / 插件元数据非法

RollbackError.__init__(errors: Sequence[BaseException], message: str | None = None)
RollbackError.errors: list[BaseException]   # 全部子异常
RollbackError.__cause__                     # 指向第一个子异常
```

## 插件契约 — `plugin.py`

```python
class Plugin(ABC):
    name: str                                    # 唯一标识，非空
    version: str = "1.0.0"
    dependencies: list[str] = []                 # 依赖插件的 name

    @abstractmethod
    async def load(self, ctx: Context) -> None   # 只注册自己
    async def enable(self) -> None               # 可安全 use() 依赖
    async def disable(self) -> None              # 默认空操作
    async def unload(self) -> None               # 自定义清理；默认空操作
```

enable/disable/unload 允许子类写成同步 `def`，内核统一调度。

## 事件总线 — `bus.py`

```python
Handler = Callable[[Any], Any]

class EventBus:
    def subscribe(self, event: str, handler: Handler) -> None
    def unsubscribe(self, event: str, handler: Handler) -> None   # 幂等
    def emit(self, event: str, data: Any = None) -> None          # 异常隔离
    def emit_async(self, event: str, data: Any = None) -> list[asyncio.Task]
    def count(self) -> int          # 有效订阅总数
    def clear(self) -> None         # 清空全部订阅
```

通配规则：`"*"` 匹配一切；`"user.*"` 匹配以 `"user."` 开头的事件（不匹配裸 `"user"`）。
`emit` 遇到协程 handler 会调度到运行中的事件循环（无循环则丢弃）。

## 服务注册表 — `registry.py`

```python
class ServiceRegistry:
    def register(self, name: str, instance: Any) -> None   # 重名抛 ServiceExistsError
    def unregister(self, name: str) -> None                # 幂等
    def use(self, name: str, default: Any = None) -> Any   # 返回实例本身
    def has(self, name: str) -> bool
    def list(self) -> list[str]                            # 服务名快照
    def clear(self) -> None
```

## 副作用追踪 — `effects.py`

```python
CleanupFn = Callable[[], None] | Callable[[], Awaitable[None]]

class EffectTracker:
    def push(self, rollback: CleanupFn) -> None
    def on(self, target: EventBus, event: str, handler: Callable) -> None
    def provide(self, registry: ServiceRegistry, name: str, instance: Any) -> None
    async def rollback(self) -> None    # LIFO；失败聚合为 RollbackError
    def count(self) -> int
    def clear(self) -> None             # 清空但不执行
```

## 插件上下文 — `context.py`

```python
class Context:
    app: App
    plugin: Plugin
    effects: EffectTracker
    config: dict[str, Any]              # app.config["plugins"][plugin.name] 的切片

    def on(self, event: str, handler: Callable) -> Self
    def emit(self, event: str, data: Any = None) -> Self
    def provide(self, name: str, instance: Any) -> Self
    def use(self, name: str, default: Any = None) -> Any
    def on_cleanup(self, callback: CleanupFn) -> Self
```

所有方法返回 `self`；`on`/`provide`/`on_cleanup` 自动登记回滚。

## 生命周期 — `lifecycle.py`

```python
PluginState = str   # "unloaded" | "loaded" | "enabled" | "disabled"

class LifecycleManager:
    def __init__(self, app: App) -> None
    async def load_all(self, plugins: list[Plugin]) -> None    # Kahn 排序
    async def enable_all(self) -> None
    async def enable(self, name: str) -> None
    async def disable(self, name: str) -> None
    async def unload(self, name: str) -> None
    async def unload_all(self) -> None                          # 逆加载顺序
    def get_state(self, name: str) -> PluginState               # 未知按 unloaded
```

状态机：`unloaded -> loaded -> enabled -> disabled -> unloaded`；
`enabled` 下 unload 先自动 disable。非法转换抛 `LifecycleError`。

## 组装器 — `app.py`

```python
class App:
    bus: EventBus
    registry: ServiceRegistry
    lifecycle: LifecycleManager
    config: dict[str, Any]           # {"plugins": {name: {...}}}

    def __init__(self) -> None
    async def start(self, plugins: list[Plugin]) -> None   # 重复 start 抛错
    async def stop(self) -> None                            # 幂等；可再次 start
    def effects_for(self, plugin_name: str) -> EffectTracker
    def discard_effects(self, plugin_name: str) -> None
```

## 公共导出 — `anima.core.__init__`

`AnimaError, App, CleanupFn, Context, DependencyError, EffectTracker,
EventBus, LifecycleError, LifecycleManager, Plugin, PluginState,
RollbackError, ServiceExistsError, ServiceNotFoundError, ServiceRegistry`

## 性能基准（实测，Windows / Python 3.13）

| 指标 | 目标 | 实测 |
|---|---|---|
| emit 平均耗时（1000 次均值） | < 0.1 ms | ~3.2 us |
| 1000 handler 单次 emit（压力口径） | < 10 ms | ~1.2 ms |
| 100 插件拓扑排序 | < 1 ms | ~0.13 ms |
| 100 插件完整生命周期 | < 50 ms | ~2.2 ms |
| EffectTracker 1000 项回滚 | < 10 ms | ~1.3 ms |
| 空 App 内存（tracemalloc 峰值） | < 5 MB | ~0.8 KiB |
