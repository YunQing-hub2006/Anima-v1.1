# Anima 内核 API 参考（v1.1.1，已冻结）

> 所有接口位于 `anima.core`，通过 `from anima.core import ...` 使用。
> 本文档为接口冻结版；任何公共接口变更需走评审流程。
> v1.1.1 变更摘要见文末"变更记录"。

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

执行顺序契约（v1.1.1 明确）：**精确订阅的 handler 先于通配 handler 执行，
两组各自内部按注册顺序执行**。同步 handler 立即执行；协程 handler 的
执行时机由事件循环调度决定，与注册顺序无关。

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
    def push_task(self, task: asyncio.Future) -> asyncio.Future   # v1.1
    def on(self, target: EventBus, event: str, handler: Callable) -> None
    def provide(self, registry: ServiceRegistry, name: str, instance: Any) -> None
    async def rollback(self) -> None    # LIFO；失败聚合为 RollbackError
    def count(self) -> int
    def clear(self) -> None             # 清空但不执行
```

`push_task`（v1.1 新增）：登记后台任务，回滚时**取消并等待其真正
结束**（先让出一个循环节拍保证协程体已启动，finally 能执行）；已
完成的任务登记后 rollback 会 re-raise 其异常（进入 RollbackError
聚合）；非 Future/Task 入参抛 `TypeError`。

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
    def task(self, coro: Coroutine) -> asyncio.Task              # v1.1
```

除 `task` 外所有方法返回 `self`；`on`/`provide`/`on_cleanup`
自动登记回滚。`task`（v1.1 新增）创建后台任务、登记"卸载时取消并
等待"的回滚，返回 Task 本身（唯一不返回 `self` 的方法）；需要运行
中的事件循环，无循环时抛 `RuntimeError`。

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

批量操作错误语义（v1.1.1 明确）：

- `load_all` / `enable_all`：某插件钩子抛异常时，已注册的全部插件
  （含失败者自身的部分副作用）按**逆加载序**尽力卸载，不留半加载
  状态。回滚干净则原样重抛原始异常（含 `CancelledError`）；回滚自身
  有清理失败则抛聚合 `RollbackError`（`__cause__` 指向原始异常，
  `errors` 只含清理失败项）。失败后可重新 `load_all`。
- `unload_all`：单插件清理失败聚合而不中断其余卸载，最后统一抛
  `RollbackError`；`_load_order` 仍清空。

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

`start` 错误语义（v1.1.1 明确）：load/enable 中途失败时，生命周期层
回滚卸载已注册插件，App 再兜底清空 bus/registry/_effects，失败后可
再次 `start`（不再残留内部状态导致"插件重复注册"）。

`stop` 错误语义（v1.1.1 明确）：单插件卸载失败聚合为 `RollbackError`
抛出，但总线/注册表清空与 `_started` 复位由 try/finally 保证必然
执行——App 始终可重启。

## 公共导出 — `anima.core.__init__`

`AnimaError, App, CleanupFn, Context, DependencyError, EffectTracker,
EventBus, LifecycleError, LifecycleManager, Plugin, PluginState,
RollbackError, ServiceExistsError, ServiceNotFoundError, ServiceRegistry`

## 性能基准（实测，Windows / Python 3.13）

| 指标 | 目标 | 实测 |
|---|---|---|
| emit 平均耗时（1000 次均值） | < 0.1 ms | ~3.1 us |
| 1000 handler 单次 emit（压力口径） | < 10 ms | ~1.2 ms |
| 100 插件拓扑排序 | < 1 ms | ~0.13 ms |
| 100 插件完整生命周期 | < 50 ms | ~2.2 ms |
| EffectTracker 1000 项回滚 | < 10 ms | ~1.3 ms |
| 空 App 内存（tracemalloc 峰值） | < 5 MB | ~1.1 KiB |

## 变更记录

### v1.1.1（2026-08-21）

三项缺陷修复，公共签名不变；批量操作的错误时行为有容错语义增强：

- `load_all`/`enable_all` 失败原子回滚（逆加载序卸载全部已注册插件），
  失败后可重新 start；回滚自身失败聚合抛 `RollbackError`。
- `unload_all` 单插件清理失败不中断其余卸载，聚合后统一抛出。
- `App.start`/`stop` 兜底清空与 `_started` 复位，始终可重启。
- `bus.py` 移除 `_wild_matches` 内不可观察的排序死代码；明确
  "精确先于通配、组内注册序"顺序契约。
- `Context.effects` 注解改为运行时导入 + 裸注解。
- 规模 785 -> 841 行；测试 113 -> 123 个；覆盖率 99% 不变。

### v1.1.0（2026-08-19）

依据 AnimaPet 迁移计划 TD2 决策表，**仅新增接口**，v1.0 公共签名与语义
不变（非破坏性变更，走 maintenance.md 冻结流程）：

- 新增 `EffectTracker.push_task(task)`：后台任务纳入 LIFO 回滚栈，
  卸载时取消并等待真正结束。
- 新增 `Context.task(coro)`：插件后台任务入口，等价
  `push_task(ensure_future(coro))`；唯一不返回 `self` 的 Context 方法。
- `bus.py` 模块 docstring 明确线程语义：跨线程同步 `emit` 安全、
  handler 在调用方线程执行、订阅约定只发生在内核线程（无代码改动）。
- 规模 735 -> 785 行；测试 104 -> 113 个；覆盖率 99% 不变。
- 类型形式 `provide(Class, ...)` / `use(Class)` 登记为演进方向，
  由框架层（AnimaPet）封装，不进内核。

### v1.0.0（2026-08-18）

初始冻结版本。9 个模块 735 行，104 个测试，覆盖率 99%。
