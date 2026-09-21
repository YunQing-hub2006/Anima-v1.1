# Anima 内核架构设计（v1.3.0）

> 本文是内核的正式架构设计文档，配合 [core_api.md](core_api.md)（接口签名）
> 与 [maintenance.md](maintenance.md)（开发维护指南）使用。
> 内核公共接口自 v1.0 起冻结，变更需走评审流程（见维护指南第 6 节）。
> v1.1 相对 v1.0 仅新增接口（`push_task`/`Context.task`）与线程语义
> 文档化，详见 core_api.md 变更记录。v1.1.2 为正确性修复 + 异常上报与
> 日志出口，同属非破坏性变更。
> v1.2 为总线健壮性（加锁）与易用性（ctx 注入 / use_strict / 热插拔），
> v1.3 为编排能力（优先级 / 请求-响应 / 生命周期事件 / 配置默认值 / 接口校验）
> 与非内核的插件自动发现，仍是纯新增。
> 同样只新增接口。

---

## 1. 设计目标与约束

| 维度 | 目标 | 达成情况 |
|---|---|---|
| 依赖 | 零外部依赖，`core/` 只 import 标准库 | ✅ 由 `check_kernel_rules.py` 自动检查 |
| 规模 | `core/` raw < 1200 / code < 650 | ✅ 1196 物理行 / **617 代码行** |
| 类型 | 所有公共接口类型注解完整 | ✅ |
| 测试 | 每模块行覆盖率 >= 90% | ✅ 总体 99%，最低模块 98% |
| 性能 | 见第 8 节基准表 | ✅ 全部达标 |
| 语义 | 插件"怎么活、怎么死、怎么通信"三件事 | — |

**非目标**（内核明确不做）：UI 框架绑定（PyQt6/PySide6 -> `anima/window/`）、
数据模型校验（Pydantic -> `anima/models/`）、文件 IO（-> `anima/utils/`）、
热重载与业务逻辑（-> `anima/plugins/`）。内核不知道"角色、聊天、天气、LLM"
是什么，任何业务概念不得出现在 `core/` 的代码、注释或异常消息中。

---

## 2. 总体分层

```
┌─────────────────────────────────────────────────┐
│                  业务插件层                       │
│        anima/plugins/（角色、聊天、天气…）        │
│              只依赖 anima.core 公共 API           │
├─────────────────────────────────────────────────┤
│                编排层（core/）                    │
│   App（组装器/唯一入口）                          │
│   LifecycleManager（拓扑排序 + 状态机）           │
│   Context（插件视角的链式入口）                    │
├─────────────────────────────────────────────────┤
│               基础设施（core/）                   │
│   EventBus（通信）  ServiceRegistry（共享）       │
│   EffectTracker（副作用回滚）                     │
├─────────────────────────────────────────────────┤
│                契约层（core/）                    │
│   Plugin（抽象基类）  exceptions（异常体系）       │
└─────────────────────────────────────────────────┘
```

依赖方向自上而下单向依赖；编排层内部 `App -> LifecycleManager -> Context`
反向通过构造注入（`LifecycleManager(app)`）避免循环 import，
跨模块类型引用一律走 `from __future__ import annotations` + `TYPE_CHECKING`。

`Plugin.ctx` 是这条规则的一个特例（v1.2）：它由编排层注入，却在契约层
声明为 `if TYPE_CHECKING:` 块内的注解——类型检查器看得见，运行时不存在
类属性，因此契约层不需要运行时 import 编排层，依赖方向保持不变。

## 3. 组件关系图

```
            ┌───────────────────────────┐
            │            App            │
            │  bus        registry      │
            │  lifecycle  config        │
            │  _effects{name: tracker}  │
            └────────┬──────────────────┘
                     │ 组装 / 委托
      ┌──────────────┼──────────────────┐
      ▼              ▼                  ▼
 LifecycleManager  Context(每插件)   EffectTracker(每插件)
  排序+状态机       链式 API          LIFO 回滚栈
      │              │                  │
      └──────────────┴──────┬───────────┘
                            ▼
        Plugin.load / enable / disable / unload
```

**所有权约定**：`App` 是唯一的 effects 持有者——`effects_for(name)` 按插件名
惰性创建追踪器，卸载完成后 `discard_effects(name)` 丢弃。`LifecycleManager`
不自有状态地反向引用 `App` 获取总线/注册表/effects，避免同一份数据两处维护。

---

## 4. 模块设计

### 4.1 exceptions.py — 异常体系

```
AnimaError
├── DependencyError        依赖缺失 / 循环依赖
├── ServiceExistsError     重复注册同名服务
├── ServiceNotFoundError   预留（严格模式 use，见 9.6）
├── RollbackError          回滚阶段聚合失败（errors: list[BaseException]）
└── LifecycleError         状态机违规 / 插件元数据非法（空名、重名、重复 start）
```

`RollbackError` 是唯一的聚合型异常：`errors` 保留全部子异常，
`__cause__` 指向第一个，默认 message 含数量与各异常摘要。

### 4.2 plugin.py — 插件契约

- `load(ctx)` 是唯一抽象方法（插件必须实现的入口）；`enable/disable/unload`
  提供异步空操作默认实现——插件"只需做自定义清理"。
- 类属性 `name / version / dependencies` 是**声明式元数据**，由内核在加载
  前统一校验，插件自身不参与校验。
- 阶段契约：`load` 只注册自己（依赖可能未加载）；`enable` 可安全 `use()`
  依赖；`disable` 只停止对外活动（**副作用保留**）；`unload` 才由框架
  统一回滚副作用（v1.1.2 修正：此前本文与 `plugin.py` 误称 disable 也
  回滚，与 `LifecycleManager.disable()` 的实现不符）。
- `dependencies` 默认值是**不可变元组** `()`（v1.1.2 起）：声明式元数据
- `config_defaults`（v1.3）同样是声明式元数据，默认值还是**只读映射**；框架在
  `load()` 前把缺失的 key 填进 `ctx.config`。
  不应让子类共享同一个可变 list。
- 同步/异步统一：三个阶段方法允许子类写成 `def`，内核 `LifecycleManager._call`
  用 `inspect.isawaitable` 分派。

### 4.3 bus.py — 事件总线

**数据结构**（性能核心决策）：

```
_exact: dict[str, list[Handler]]        # 精确事件，O(1) 查找
_wild:  list[tuple[prefix, Handler]]    # 通配订阅，emit 时线性扫描
```

**匹配规则**：`"user.*"` 归一化为前缀 `"user."`（匹配 `user.click`，
不匹配裸 `user`）；`"*"` 归一化为空前缀（匹配一切）。

**异常隔离**：每个 handler 调用独立 `try/except Exception`，单个崩溃不影响
同事件的其他 handler，也不向 emit 调用方传播。

**协程 handler 策略**：
- `emit`（同步）：协程结果调度到**运行中的**事件循环（`create_task`）；
  无事件循环时关闭协程并丢弃——同步 emit 永不阻塞。
- `emit_async`：协程包装为 `Task` 返回，由调用方 `gather`；同步 handler
  仍立即执行。

**异常上报（v1.1.2）**：异常隔离不等于静默。每个 handler 的异常在
`except` 后交给 `_report`：有 `on_error` 钩子则用钩子，否则写
`anima.bus` logger。`_report` 整体包在 try/except 内——钩子是用户
代码，它崩了也只能写日志，绝不把异常漏给发布方。

**线程安全（v1.2）**：订阅表由 `threading.RLock` 保护。关键是**锁不
跨越 handler 执行**——`_handlers` 在锁内拷出列表后立即释放，handler 仍在
调用方线程运行。这样既保证了任意线程增删订阅安全，又不会让慢 handler
阻塞别人的订阅、也不会让 handler 内的 subscribe 死锁（ADR 15）。

**`emit_and_wait`（v1.2）**：`emit_async` 的配套便捷方法——
`emit_async` 把协程 handler 包成 Task 返回，调用方一旦忘记 await，任务就可能
在 GC 时被静默丢弃；`emit_and_wait` 内部 `gather(return_exceptions=True)`，

**优先级与请求-响应（v1.3）**：`subscribe(..., priority=n)` 让 n 大的先执行，
同优先级仍按注册顺序（稳定排序），“精确组整体先于通配组”不变；只有用过
非零 priority 才排序。`emit_collect()` 收集全部 handler 的返回值（同步直接、
协程 await），异常仍按 handler 隔离。
是“发布并等它跑完”这个常见用法的正确默认。

### 4.4 registry.py — 服务注册表

薄字典封装，三个关键语义：重复注册抛 `ServiceExistsError`（防止隐性覆盖）、
`unregister` 幂等（与回滚路径配合，重复回滚安全）、`use` 返回实例本身不包装。

v1.2 增加**严格获取** `use_strict(name)`：未注册时抛 `ServiceNotFoundError`。
`use()` 的 default 语义不变——它是冻结接口，收紧属破坏性变更（ADR 16）。

### 4.5 effects.py — 副作用追踪

LIFO 栈 + 逐项回滚：

- `on(bus, ...)` = subscribe + push(unsubscribe)；`provide(registry, ...)` =
  register + push(unregister)——复合副作用与手工 push 走同一条回滚路径。
- `rollback()` 逐项 pop 执行（同步直调、异步 await）；**单项失败继续**，
  全部执行完后栈必空，若有失败统一抛 `RollbackError(errors)`。
- `clear()` 只清空不执行（用于测试与强制丢弃）。

### 4.6 context.py — 插件上下文

- 每个插件 `load` 时构造一个，是插件看到内核的**唯一窗口**
  （不暴露 bus/registry 内部结构）。
- 全部方法返回 `self` 支持链式调用；`on/provide/on_cleanup` 自动登记回滚。
- `config` 是 `app.config["plugins"][plugin.name]` 的**引用切片**：缺失时
  自动建空 dict，各插件子 dict 天然隔离；`start` 前注入的配置对插件可见。
- **v1.2 `ctx` 注入**：框架在 `load()` 前写 `plugin.ctx = ctx`，
  三个阶段方法都能直接用 `self.ctx`，插件不必自己保存 load 的参数；
  重启（stop 后再 start）会注入新的 Context。
- **v1.2 `use_strict()`**：取不到服务就抛，把“忘 provide / 拼错名字”
- **v1.3**：`config_defaults` 填配置默认值；`provide` / `use` / `use_strict` 支持
  `interface` 校验；新增 `emit_and_wait` / `emit_collect`——Context 是插件唯一窗口，
  总线上的发布方法在这里都有对应入口。
  从“使用时才炸”提前到“取用点就炸”。

### 4.7 lifecycle.py — 生命周期管理器（内核最复杂的模块）

三块职责：

**a) 加载前校验（检测前移）**——在任何插件代码执行前完成：
空名、同批次/跨批次重名 -> `LifecycleError`；依赖缺失、循环依赖 ->
`DependencyError`。插件永远不会观察到"半加载"中间态。

**b) Kahn 拓扑排序**：构建 `依赖 -> 被依赖` 边，入度 0 入队，处理后消减下游
入度；队空仍有剩余节点即有环，报出全部环上插件名。O(V+E)。

**c) 状态机**：

```
unloaded ──load──> loaded ──enable──> enabled
   ^                  ^                   │
   │                  └────disable────────┤
   └────────unload（enabled 下先自动 disable）┘
```

- **生命周期事件（v1.3）**：每次成功转换后发 `kernel.plugin.loaded` / `enabled` /
  `unloaded`（payload 为插件名）；`unloaded` 在副作用回滚之后，卸载者自己收不到。
- 合法转换之外的任何操作抛 `LifecycleError`；未知插件名同样抛错
  （`get_state` 例外：未知按 `unloaded` 返回）。
- `enable_all` 按加载顺序启用（依赖先于依赖方启用）；
  `unload_all` 按**逆加载顺序**先 disable 全部再卸载。

**卸载的错误语义**（关键决策）：`unload(name)` = 回滚 effects ->
调用 `plugin.unload()` -> 状态推进到 `unloaded`。两步的异常都收进同一个
`RollbackError` 抛出，但**状态照样推进**——清理是尽力而为，失败不把
插件卡在中间态，也不阻止其他插件卸载。

### 4.8 app.py — 组装器

- `__init__` 创建 bus/registry/lifecycle 与 `config = {"plugins": {}}`。
- `start`：`load_all -> enable_all`；运行中重复 `start` 抛 `LifecycleError`。
  load/enable 中途失败时，生命周期层按逆加载序回滚已注册插件；
  App 层再兜底清空 bus/registry/_effects，保证失败后可再次 `start`。
- `stop`：`unload_all` 包在 try/finally 中，卸载异常也必然执行
  `bus.clear() -> registry.clear() -> effects 清空 -> _started=False`；
  未启动时是空操作，stop 后可再次 start（可重启、不泄漏）。
- start 因依赖错误失败后，`stop` 仍可安全调用（幂等兜底）。
- **单插件热插拔（v1.2）**：`load_plugin(plugin)` / `unload_plugin(name)` 在
  运行中装卸单个插件，要求 App 已 `start`。新插件的依赖只能指向**已加载**
  的插件；加载失败只回滚这一个插件（`load_one`），不会波及在跑的插件。
  `unload_plugin` 在仍有插件依赖目标时抛 `LifecycleError`（不做级联卸载）——
  直接放行会留下“服务已注销、插件还在跑”的破洞状态。

---

## 5. 关键横切机制

### 5.1 同步/异步统一调用模型

内核是 async-first 的，但允许插件与 handler 写同步代码以降低业务侧成本：

| 调用点 | 机制 |
|---|---|
| 插件生命周期方法 | `_call()`：`inspect.isawaitable(result)` 决定是否 await |
| EffectTracker cleanup | 同上，同步/异步 cleanup 可混合入栈 |
| 总线 handler | `emit` 按 `iscoroutine(result)` 分派；`emit_async` 包装为 Task |
| 后台任务（v1.1） | `ctx.task(coro)` 创建 Task 并纳入回滚栈，卸载时 cancel+await |

### 5.2 异常处理策略总表

| 场景 | 行为 | 理由 |
|---|---|---|
| 单个事件 handler 抛异常 | **隔离**（不上抛），其他 handler 照常；经 `on_error` 上报（默认 `anima.bus` logger） | 发布方不应为订阅者买单，但也不该无声失败 |
| `on_error` 上报钩子自身抛异常 | 隔离，退回默认 logger 上报 | 上报路径不得破坏 emit 的"永不失败"契约 |
| `use_strict` 取不到服务 | 抛 `ServiceNotFoundError` | 严格获取的语义就是"取不到即失败"，与 `use` 的 default 语义并存 |
| `unload_plugin` 仍有依赖方 | 抛 `LifecycleError`，拒绝卸载 | 宁可拒绝也不留破洞中间态（同 ADR 2 检测前移） |
| 单个 cleanup 抛异常 | 继续回滚剩余项，最后聚合 | 回滚完整性 > 单项成功 |
| `plugin.unload()` 抛异常 | 收集进 RollbackError，状态仍 unloaded | 不让坏插件卡死全局 |
| 依赖缺失/循环 | 加载前抛 DependencyError | 插件代码执行前拦截 |
| 非法状态转换 | 抛 LifecycleError | 状态机显式失败 |
| 重复 start | 抛 LifecycleError | 防止重复副作用 |
| 重复 unsubscribe/unregister | 静默（幂等） | 与自动回滚路径配合必须安全 |
| `plugin.load()` / `enable()` 抛异常 | 已注册插件逆序回滚卸载；回滚干净时重抛原始异常，回滚清理失败时抛聚合 RollbackError（cause 指向原始异常） | 批量启动原子性，不留半加载状态 |
| `unload_all` 中单插件清理失败 | 聚合不中断，其余插件照常卸载，最后统一抛 RollbackError | 卸载完整性 > 单项失败 |

### 5.3 副作用回滚语义

```
push 顺序:  provide("db")  ->  on("tick")  ->  task(coro)
回滚顺序:   cancel+await(task)  ->  unsubscribe("tick")  ->  unregister("db")
```

后产生的副作用依赖先产生的（例如先 provide 服务再订阅用到该服务的事件），
LIFO 保证拆卸顺序与建立顺序严格互逆。

v1.1 的 `push_task` 把"取消并等待后台任务"作为一条普通 cleanup 入栈，
复用 LIFO/异常聚合两条不变式。关键细节：cancel 请求若落在**从未启动**
的协程上，协程体（含 finally）不会执行，因此回滚代码先 `await sleep(0)`
让出一拍、保证协程进入函数体后再 cancel；任务自身的非 CancelledError
异常进入 RollbackError 聚合，不阻断其他回滚。**已取消的任务（v1.1.2
明确）直接跳过**：`await` 一个已取消的 Task 会抛回 `CancelledError`，
而 `rollback()` 只捕获 `Exception`，那会打断整条回滚链并让其余插件永不
卸载。

---

## 6. 数据流

### 6.1 启动（App.start）

```
App.start(plugins)
  ├─ LifecycleManager.load_all(plugins)
  │    ├─ 校验：name 非空、无重名（LifecycleError）
  │    ├─ Kahn 拓扑排序
  │    │    缺失依赖 / 环 ──────────────> DependencyError（加载前拦截）
  │    └─ 依序对每个插件:
  │         state=loaded; Context(app, plugin) 构造
  │         plugin.load(ctx)
  │              ctx.provide(name, svc) ──> registry.register + tracker.push
  │              ctx.on(evt, handler)  ──> bus.subscribe   + tracker.push
  │              load() 抛异常 ──────────> 已注册插件逆序回滚卸载
  │                                        （含失败者自身的部分副作用）
  │                                        回滚失败聚合 RollbackError
  │                                        （cause 指向原始异常）
  ├─ LifecycleManager.enable_all()   # 依赖方保证晚于其依赖启用
  │    └─ plugin.enable()            # 此阶段 ctx.use() 安全
  │         enable() 抛异常 ──────────> 同上逆序回滚卸载
  └─ 成功: App._started = True
     失败: App 兜底 bus.clear()/registry.clear()/_effects.clear()，可重试
```

### 6.2 停止（App.stop，逆序回滚）

```
App.stop()
  ├─ LifecycleManager.unload_all()   # 逆加载（拓扑）顺序
  │    └─ 对每个插件（enabled 的先 disable）:
  │         ├─ EffectTracker.rollback()   # LIFO，失败聚合
  │         ├─ plugin.unload()            # 插件自定义清理
  │         └─ state=unloaded; App.discard_effects(name)
  │    # 单插件清理失败不中断其余卸载，最后统一抛 RollbackError
  └─ finally（即使 unload_all 抛异常也执行）:
       ├─ bus.clear(); registry.clear(); _effects.clear()
       └─ _started = False（可再次 start，不泄漏状态）
```

### 6.3 事件发布

```
emit("user.click", d):
  handlers = _exact.get("user.click", [])
            + [h for prefix, h in _wild if "user.click".startswith(prefix)]
  逐个调用，try/except 隔离；协程结果调度到事件循环
emit_async: 同上，协程包装为 Task 返回给调用方 gather
```

---

## 7. 并发模型

- **线程语义（v1.2 定稿）**：`EventBus` 的订阅表由 `threading.RLock` 保护，
  `subscribe` / `unsubscribe` / `count` / `clear` / `_handlers` 都在锁内
  操作，因此**任意线程增删订阅都是安全的**。v1.1 时这条只靠“订阅只发生在
  内核线程”的口头约定，v1.2 起由代码保证。
  - **锁不跨越 handler 执行**：`_handlers` 在锁内拷出列表后立即释放，
    handler 在**调用方线程**运行。因此 handler 里再 subscribe / emit 不会
    死锁，慢 handler 也不会阻塞其他线程的订阅——这是加锁方案能成立的前提
    （ADR 15）。
  - **从任意线程同步调用 `bus.emit` 是安全的**——handler 在**调用方线程**
    立即执行（AnimaPet 的 Qt 主线程 emit → 规则引擎同步触发 → bridge
    同步更新 UI，全程不离开调用线程）。
  - **跨线程 `emit` 的协程 handler 不会被调度**：调度依赖
    `asyncio.get_running_loop()`，它是线程局部的；UI 线程没有运行中的内核
    循环时，协程结果被丢弃（与 v1.0 行为一致）。需要跨线程唤醒协程时仍由
    使用者用 `loop.call_soon_threadsafe`。
  - `count()` 是瞬时快照：并发增删下只保证“某一刻的近似值”。
- **`ServiceRegistry` / `EffectTracker` 未加锁**：二者仍约定由内核线程独占写入
  （插件 load/unload 都发生在内核线程）；`use`（只读 dict 查找）从任意线程安全。
  EventBus 是唯一被 UI 线程直接触碰的组件，所以只有它需要锁。
- `emit` 在无运行循环时收到协程 handler 会丢弃该协程（并 close），
  保证同步上下文调用永不失败。
- 真正的 `emit_threadsafe` 网关仍登记为演进方向（见 §10），v1.1 不提供。

---

## 8. 性能设计

| 决策 | 收益 | 实测 |
|---|---|---|
| 精确事件 dict 索引 | O(1) 查找 | emit 平均 **0.78 µs**（目标 <100µs） |
| 通配独立列表（非逐模式正则） | 扫描成本与订阅数线性 | 200 通配下精确事件不受影响 |
| Kahn 排序 O(V+E)，入度数组 | 100 插件 **0.07 ms**（目标 <1ms） |
| 回滚为简单 pop 循环 | 1000 项 **0.38 ms**（目标 <10ms） |
| App 惰性创建 effects | 空 App 峰值 **1.6 KiB**（目标 <5MB） |
| 100 插件完整生命周期 | 全流程 **0.47 ms**（目标 <50ms） |

注：计划中"1000 handler emit <0.1ms"按其"测 1000 次取平均"口径执行；
1000-handler 单次 emit 作为压力项单独设 10ms 上限（实测 1.2ms）。
基准脚本位于 `tests/test_core/test_performance.py`，阈值含 5 倍安全系数。

v1.2 给订阅表加锁后实测 emit 平均 **0.78 µs**，仍远低于 <100 µs 目标——锁只在
开头读一次订阅表，**不在 handler 执行期间持有**，因此与 handler 的耗时无关。
本次数值与表中历史值（v1.0 记录为 3.1 µs）差异主要来自机器与测法，按 §7 的
约定：**阈值才是回归依据，绝对值只作参考**。

---

## 9. 设计决策记录（ADR 摘要）

1. **enabled 下 unload 自动 disable**：让单插件卸载与 `unload_all` 走同一条
   路径，状态机在容错方向闭合。代价是"隐式转换"，已在接口文档标注。
2. **检测前移**（重名/空名/缺失/循环在插件代码执行前拦截）：插件不会观察到
   半加载状态，失败恢复（直接 `stop()`）最简单。
3. **App 持有 effects，LifecycleManager 反向引用 App**：避免 effects 归属
   二义性；`Context` 构造时从 App 取，保证同一插件拿到同一追踪器。
4. **`use()` 返回 default 而非抛 ServiceNotFoundError**：enable 阶段依赖
   已由拓扑排序保证存在，抛错路径反而是噪音；异常保留给未来的严格模式。
5. **卸载失败状态仍推进**：清理尽力而为，状态不卡死；错误通过
   `RollbackError.errors` 完整上报，由调用方决定如何记录。
6. **`load()` 抽象而其余阶段给默认实现**：强制插件声明入口，同时把"没有
   自定义清理"的成本降为零。
7. **协程 handler 在同步 `emit` 下调度而非报错**：发布方无需关心订阅者是
   同步还是异步；无循环时丢弃是显式选择的保守行为。
8. **v1.1 `push_task` 先 `sleep(0)` 再 cancel**：cancel 请求落在从未启动
   的协程上时，异常在函数定义点抛出、协程体（含 finally）不执行——
   因此回滚必须先让出一拍让协程进入函数体，否则"卸载时清理"承诺失效。
   代价是多一个循环节拍的延迟，对回滚路径可接受。
9. **v1.1 `Context.task` 不返回 self**：链式 API 的唯一例外，因为调用方
   需要 Task 引用做进一步控制（await / add_done_callback）。docstring 与
   core_api.md 显式标注，避免后人误改。
10. **v1.1.1 start 原子回滚**：load/enable 钩子失败时，已注册插件按逆
    加载序尽力卸载，不留半加载状态。此前 ADR 2 的"失败恢复（直接
    stop()）最简单"假设被 `stop()` 的 `_started` 早返回打破——半加载
    状态不可达。修复后该承诺真正成立：失败后可再次 `start`。回滚自身
    的清理失败聚合进 `RollbackError`（`__cause__` 指向原始异常），
    不静默。
11. **v1.1.1 handler 顺序契约**：精确 handler 先于通配 handler，组内
    按注册顺序。此前 `_wild_matches` 只对通配 handler 做 sync-before-
    async 排序而精确 handler 不排序，但该排序不可观察（异步 handler
    从不内联执行），属死代码，已移除。契约写入 bus.py docstring 并以
    `test_handler_order_contract` 锁死，演进方向若引入真正的优先级
    排序需显式设计。
12. **v1.1.2 handler 异常上报与隔离并存**：隔离的语义是"不上抛给发布
    方"，不是"无声"。给 `EventBus` 加可选 `on_error` 钩子，默认写
    `anima.bus` logger。为什么不直接把异常抛出去？见 §5.2 第 1 行——
    发布方不应为订阅者买单。为什么钩子也要 try/except？因为它是用户
    代码，一旦它抛异常，隔离就被从后门打破。
13. **v1.1.2 `disable()` 语义按实现定稿**：`disable` **不回滚**副作用。
    曾考虑让 disable 也回滚，但那要求 `enable` 重放订阅（把
    EffectTracker 拆成"持久区/临时区"），API 复杂度显著上升，而收益
    只是语义洁癖。最终选择修正文档而非改代码：disable = 停止主动做事，
    unload = 卸下向内注册。
14. **v1.1.2 循环依赖报错报"环"而非"剩余节点"**：Kahn 结束后入度仍 > 0
    的节点包含"仅被环拖累"的下游插件。报出它们会把排查者引向无辜
    插件，因此额外用三色 DFS 回溯一条真实环路，消息即
    `a -> b -> a`。
15. **v1.2 给 EventBus 加锁，并推翻 v1.1 的“不加锁”结论**：v1.1 明确写了
    “总线内部无锁……危险模式是多线程并发 subscribe，框架层约定订阅只发生在
    内核线程”，甚至提示“避免后人误加锁”。该结论在“所有订阅都来自内核线程”
    成立时正确，但它是**约定而非机制**——一旦有人从 UI 线程订阅（或未来出现
    热重载线程），就是难以复现的竞态。v1.2 用 RLock 把它变成机制，同时靠
    “锁内拷贝、锁外执行”保住 v1.1 真正在意的两件事：handler 仍在调用方线程
    运行、慢 handler 不阻塞任何人。ADR 的结论可以改，但必须写清为什么改。
16. **v1.2 用 `use_strict` 而不是收紧 `use()`**：外部评审把“use() 未注册返回
    None 导致错误延迟暴露”列为易用性问题，建议改成抛异常。这是破坏性变更
    （调用方的错误处理会失效），按 maintenance.md §6 只能走“新增过渡接口”——
    于是加 `use_strict()`，`use()` 的 default 语义冻结到下一个主版本。这是
    §6 流程的第一个实际用例。
17. **v1.2 热插拔的失败半径与卸载守卫**：`load_one` 失败**只回滚自己**——绝不能
    复用它家的 `_raise_with_rollback_errors`，那会把整台 App 卸掉；
    `unload_plugin` 在有依赖方时**拒绝执行**而非级联卸载——级联会静默卸掉
18. **v1.3 优先级做成“零成本默认”**：事件顺序是有契约的（精确先于通配、
    组内注册序），加优先级不能动它。于是把 priority 默认 0、只在真的用过非零值
    时才排序（`_prioritized`）——老代码的路径一行没变，两条契约测试也都不用改。
19. **v1.3 生命周期事件在副作用回滚之后发**：`unloaded` 若发在回滚之前，卸载中的
    插件会收到自己的讣告，而它的状态位此时已经不确定。放到回滚之后，语义干净：
    收到事件的人一定还活着。
20. **v1.3 自动发现不进内核**：entry points 属于“怎么装载插件”，不是
    “插件怎么活/怎么死/怎么通信”；而且内核物理行只剩个位数余量。放
    `anima/plugins/` 里，`check_kernel_rules.py` 只管 `core/`，两边都干净。
    用户没点名的插件，比直接报错更难排查。

---

## 10. 扩展点与演进方向（未实施，仅登记）

| 方向 | 说明 | 接入点 |
|---|---|---|
| 线程安全总线 | ✅ 订阅表已加锁（v1.2）；剩余的 `emit_threadsafe()`（协程 handler 的跨线程调度网关）未做 | bus.py |
| 严格服务获取 | ✅ v1.2 已实施：`use_strict()` 抛 `ServiceNotFoundError`，`use()` 语义冻结 | registry.py |
| 单插件热插拔 | ✅ v1.2 已实施：`App.load_plugin` / `unload_plugin`（替换式重载仍需新实例） | app.py |
| 插件自动发现 | ✅ v1.3 已实施：`anima/plugins/discovery.py`（entry points，非内核） | plugins/ |
| 类型形式 provide/use | ✅ v1.3 部分实施：`provide/use(interface=T)` 做运行时校验；类键形式 | plugins 层 |
| 插件热重载 | 文件监听属 `anima/plugins/hotreload.py`，内核不需改动 | plugins/ |
| 事件优先级/延迟 | ✅ v1.3 已实施显式 `priority`（零成本默认）；延迟（defer）仍未做 | bus.py |
| 条件启用 | config 切片加 `enabled: false` 约定 | lifecycle.py |

> **规模口径（v1.2 起）**：`check_kernel_rules.py` 强制两条——`raw < 1200` 物理
> 行 + `code < 650` 代码行（去掉空行、注释与 docstring）。原先单条
> `raw < 1000` 在 docstring 变详细后开始失真：1.1.2 结束时 961 物理行其实只有
> 约 500 行代码，而迭代 2 的新增直接把它顶到 1104。拆分后物理行防文件膨胀，
> **代码行才是“内核保持小巧”的守门指标**。当前 1104 / 553，余量约 96 物理行、
> 33 代码行（v1.3.0 后：物理行仅剩 4 行）。

任何演进若改动冻结接口，必须走第 6 节（维护指南）的变更评审流程。
