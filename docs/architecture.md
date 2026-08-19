# Anima 内核架构设计（v1.1）

> 本文是内核的正式架构设计文档，配合 [core_api.md](core_api.md)（接口签名）
> 与 [maintenance.md](maintenance.md)（开发维护指南）使用。
> 内核公共接口自 v1.0 起冻结，变更需走评审流程（见维护指南第 6 节）。
> v1.1 相对 v1.0 仅新增接口（`push_task`/`Context.task`）与线程语义
> 文档化，详见 core_api.md 变更记录。

---

## 1. 设计目标与约束

| 维度 | 目标 | 达成情况 |
|---|---|---|
| 依赖 | 零外部依赖，`core/` 只 import 标准库 | ✅ 由 `check_kernel_rules.py` 自动检查 |
| 规模 | `core/` < 1000 行 | ✅ 785 行 |
| 类型 | 所有公共接口类型注解完整 | ✅ |
| 测试 | 每模块行覆盖率 >= 90% | ✅ 总体 99%，最低模块 97% |
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
  依赖；`disable/unload` 框架先自动回滚副作用。
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

### 4.4 registry.py — 服务注册表

薄字典封装，三个关键语义：重复注册抛 `ServiceExistsError`（防止隐性覆盖）、
`unregister` 幂等（与回滚路径配合，重复回滚安全）、`use` 返回实例本身不包装。

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
- `stop`：`unload_all -> bus.clear() -> registry.clear() -> effects 清空`；
  未启动时是空操作，stop 后可再次 start（可重启、不泄漏）。
- start 因依赖错误失败后，`stop` 仍可安全调用（幂等兜底）。

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
| 单个事件 handler 抛异常 | 吞掉，其他 handler 照常 | 发布方不应为订阅者买单 |
| 单个 cleanup 抛异常 | 继续回滚剩余项，最后聚合 | 回滚完整性 > 单项成功 |
| `plugin.unload()` 抛异常 | 收集进 RollbackError，状态仍 unloaded | 不让坏插件卡死全局 |
| 依赖缺失/循环 | 加载前抛 DependencyError | 插件代码执行前拦截 |
| 非法状态转换 | 抛 LifecycleError | 状态机显式失败 |
| 重复 start | 抛 LifecycleError | 防止重复副作用 |
| 重复 unsubscribe/unregister | 静默（幂等） | 与自动回滚路径配合必须安全 |

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
异常进入 RollbackError 聚合，不阻断其他回滚。

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
  ├─ LifecycleManager.enable_all()   # 依赖方保证晚于其依赖启用
  │    └─ plugin.enable()            # 此阶段 ctx.use() 安全
  └─ App._started = True
```

### 6.2 停止（App.stop，逆序回滚）

```
App.stop()
  └─ LifecycleManager.unload_all()   # 逆加载（拓扑）顺序
       └─ 对每个插件（enabled 的先 disable）:
            ├─ EffectTracker.rollback()   # LIFO，失败聚合
            ├─ plugin.unload()            # 插件自定义清理
            └─ state=unloaded; App.discard_effects(name)
  ├─ bus.clear(); registry.clear()
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

- **v1.1 线程语义（正式结论）**：`EventBus`、`ServiceRegistry`、
  `EffectTracker` 内部是普通 dict/list，未加锁；但单个 `emit` /
  `subscribe` / `unregister` 调用是纯同步代码，**无 await 临界区**，
  在 CPython GIL 下是原子的。因此：
  - **从任意线程同步调用 `bus.emit` 是安全的**——handler 在**调用方线程**
    立即执行（AnimaPet 的 Qt 主线程 emit → 规则引擎同步触发 → bridge
    同步更新 UI，全程不离开调用线程）。
  - **跨线程 `emit` 的协程 handler 不会被调度**：调度依赖
    `asyncio.get_running_loop()`，它是线程局部的；UI 线程没有运行中的
    内核循环时，协程结果被丢弃（与 v1.0 行为一致）。
  - **危险模式是多线程并发 subscribe 同一事件**造成的 list 竞争。
    框架层约定：**订阅只发生在插件 load/unload（内核线程）**，
    UI 线程只 emit。该约定写入了 bus.py 的模块 docstring。
- **多线程并发 use/register** 不安全：ServiceRegistry 同理约定由
  内核线程独占写入；`use`（只读 dict.get）从任意线程安全。
- `emit` 在无运行循环时收到协程 handler 会丢弃该协程（并 close），
  保证同步上下文调用永不失败。
- 真正的 `emit_threadsafe` 网关仍登记为演进方向（见 §10），v1.1 不提供。

---

## 8. 性能设计

| 决策 | 收益 | 实测 |
|---|---|---|
| 精确事件 dict 索引 | O(1) 查找 | emit 平均 **3.2 µs**（目标 <100µs） |
| 通配独立列表（非逐模式正则） | 扫描成本与订阅数线性 | 200 通配下精确事件不受影响 |
| Kahn 排序 O(V+E)，入度数组 | 100 插件 **0.13 ms**（目标 <1ms） | |
| 回滚为简单 pop 循环 | 1000 项 **1.3 ms**（目标 <10ms） | |
| App 惰性创建 effects | 空 App 峰值 **0.8 KiB**（目标 <5MB） | |
| 100 插件完整生命周期 | 全流程 **2.2 ms**（目标 <50ms） | |

注：计划中"1000 handler emit <0.1ms"按其"测 1000 次取平均"口径执行；
1000-handler 单次 emit 作为压力项单独设 10ms 上限（实测 1.2ms）。
基准脚本位于 `tests/test_core/test_performance.py`，阈值含 5 倍安全系数。

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

---

## 10. 扩展点与演进方向（未实施，仅登记）

| 方向 | 说明 | 接入点 |
|---|---|---|
| 线程安全总线 | `emit_threadsafe()` 经 `loop.call_soon_threadsafe`（v1.1 已文档化跨线程同步 emit 安全，此项为协程 handler 的跨线程调度网关） | bus.py |
| 严格服务获取 | `use_strict()` 抛 `ServiceNotFoundError`（已预留） | registry.py |
| 类型形式 provide/use | `ctx.provide(ConfigService, ...)`（v1.1 登记为框架层封装，不进内核） | plugins 层 |
| 插件热重载 | 文件监听属 `anima/plugins/hotreload.py`，内核不需改动 | plugins/ |
| 事件优先级/延迟 | handler 包装排序（`_wild_matches` 已有排序钩子位） | bus.py |
| 条件启用 | config 切片加 `enabled: false` 约定 | lifecycle.py |

任何演进若改动冻结接口，必须走第 6 节（维护指南）的变更评审流程。
