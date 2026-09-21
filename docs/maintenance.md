# Anima 内核开发维护指南

> 面向内核的后续维护者：如何搭建环境、如何遵循开发流程、如何安全地
> 改动内核、如何诊断常见问题。架构背景见 [architecture.md](architecture.md)，
> 接口签名见 [core_api.md](core_api.md)。

---

## 1. 环境搭建

```bash
# Windows（仓库自带 .venv，Python 3.13）
cd E:\Zcode-work\work
.venv\Scripts\python -m pytest tests/test_core/ -v        # 全量测试
.venv\Scripts\python -m pytest tests/test_core/ --cov=anima.core --cov-report=term
.venv\Scripts\python check_kernel_rules.py                 # 铁律自动检查

# 若需重建环境
python -m venv .venv
.venv\Scripts\python -m pip install pytest pytest-asyncio pytest-cov
```

开发依赖只有三个（均为测试工具，永不进入 `core/` 的 import）：
`pytest`、`pytest-asyncio`（`asyncio_mode=auto` 已在 pyproject 配置）、
`pytest-cov`。

## 2. 仓库地图

```
anima/core/            内核（1104 物理行 / 553 代码行，纯标准库，接口已冻结）
  app.py               组装器：start/stop、effects 持有者
  bus.py               事件总线：_exact dict + _wild 列表 + 异常上报钩子
  registry.py          服务注册表
  lifecycle.py         校验 + Kahn 排序 + 状态机 + 卸载（最复杂，改动最谨慎）
  context.py           插件上下文（链式 API）
  effects.py           LIFO 副作用栈
  plugin.py            插件 ABC
  exceptions.py        异常体系
  log.py               日志出口（anima logger，v1.1.2）
tests/test_core/       173 个测试，14 个文件，按被测模块命名
  conftest.py          bus/registry/effects/app fixtures + RecorderPlugin
  test_performance.py  性能基准（阈值 = 目标值 x5 安全系数）
  test_edge_cases.py   边界 + 压力
docs/                  architecture / core_api / maintenance 三份文档
examples/              可运行示例（hello / dependency / rollback / hot_reload）
check_kernel_rules.py  铁律检查（raw<1200 + code<650、无第三方 import）
pyproject.toml         pytest/coverage 配置
```

## 3. 内核铁律（改动前自查清单）

1. `core/` 的 import 只允许标准库和 `anima` 自身 -- `check_kernel_rules.py` 会拦。
2. 内核不得出现业务概念（角色/聊天/天气/LLM），包括注释和异常消息。
3. 只回答三件事：插件怎么活、怎么死、怎么通信。
4. 所有公共接口类型注解完整（含返回值；链式方法返回 `Self`）。
5. 每模块行覆盖率 >= 90%，新分支必须有对应用例。
6. 任何 handler / cleanup 抛异常不得影响其他组件（异常隔离不变式）。
7. `unregister` / `unsubscribe` 幂等（自动回滚路径依赖这一点）。
8. `core/` 规模满足**两个口径**（v1.2 起，由 `check_kernel_rules.py` 强制）：
   `raw < 1200` 物理行、`code < 650` 代码行（去掉空行/注释/docstring）。
   物理行防文件膨胀，**代码行才是“内核保持小巧”的守门指标**——本内核
   docstring 占比约五成，只看物理行会在文档变详细后失真。
   加功能前先想能不能放到 `anima/plugins/` 或 `anima/utils/`（默认答案
   通常是“能”）；新增公共能力前先估代码行数。

## 4. 开发流程（测试先行）

任何内核改动的标准节奏：

```
1. 在对应 tests/test_core/test_<模块>.py 先写失败测试
2. 实现/修改 anima/core/<模块>.py
3. 全量回归：pytest tests/test_core/ -v        （必须全绿）
4. 覆盖率复查：--cov-report=term               （该模块 >= 90%）
5. 铁律检查：python check_kernel_rules.py
6. 若改了公共接口 -> 先走第 6 节变更评审，再动代码
7. 按里程碑提交，commit message 说明"改了什么 + 为什么"
```

**断言风格**：优先断言行为（收到什么事件、状态是什么、栈是否清空），
不 assert 内部数据结构（`_exact` 的形状可能变，回滚语义不会）。

## 5. 各模块修改注意事项

### bus.py
- 通配语义固定：`"user.*"` 匹配以 `"user."` 开头的一切、不匹配裸 `"user"`；
  `"*"` 匹配一切。改匹配规则属破坏性变更。
- **顺序契约（v1.1.1 锁定）**：精确 handler 先于通配 handler，组内按
  注册顺序——由 `test_handler_order_contract` 锁死。若引入真正的优先级
  排序，必须先过该测试再显式设计；`_wild_matches` 内不再有任何排序。
- 新增订阅结构时同步维护 `count()`/`clear()`，`App.stop` 的"bus 为空"
  验收依赖 `count()` 正确。
- emit 的异常隔离必须保持：改 handler 调度时先读 `test_handler_exception_isolation`。
- **v1.1.2 异常上报**：handler 异常依旧不上抛，但必须经 `_report` 走
  `on_error` 钩子（默认 `anima.bus` logger）。**上报路径本身也不能抛**
  ——钩子是用户代码。锁死用例：
  `test_error_hook_receives_handler_exception`（emit 路径）、
  `test_error_hook_covers_emit_async_sync_handler`（emit_async 的同步
  handler 路径）、`test_error_hook_failure_does_not_escape` /
  `..._emit_async`（钩子自身崩溃不得外泄）。
- `EventBus.__init__` 的 `on_error` 与 `set_error_hook` 是 v1.1.2 新增
  的可选能力；默认值 `None` 表示"用默认 logger 上报"，不要改成"静默"。
- **v1.2 加锁**：订阅表由 `threading.RLock` 保护。唯一不可违反的设计是
  **锁不跨越 handler 执行**——`_handlers` 必须在锁内拷出列表后立刻释放，
  否则慢 handler 会阻塞所有线程的订阅、handler 内 subscribe 会死锁。
  锁死用例：`test_lock_is_not_held_during_handler_execution`（handler 卡住
  时另一线程仍能订阅）、`test_handler_can_subscribe_reentrantly`、
  `test_concurrent_subscribe_unsubscribe_stress`。
- `emit_and_wait`（v1.2）只是 `emit_async` 加 `gather(return_exceptions=True)`
  的便捷封装；不要把它改成“等同步 handler”，同步 handler 一直就是立即执行。

### plugin.py
- `dependencies` 默认值是**不可变元组**（`ClassVar[Sequence[str]] = ()`，
  v1.1.2 起）。v1.1.1 及以前是 `list[str] = []`——类属性，所有子类共享
  同一个 list，任何 `self.dependencies.append(...)` 会污染全局。锁死用例
  `test_dependencies_default_is_immutable_and_unshared`，不要改回 list。
- **生命周期文档即契约**：`disable()` 不回滚副作用，只有 `unload()` 回滚。
  改这里必须同步 `architecture.md` §4.2 与 `core_api.md`（v1.1.2 修过一次
  这种"文档与实现裂缝"）。

### registry.py / effects.py
- `use()` 返回 default、`unregister` 幂等，这两个语义被 Context 与自动回滚
  依赖，不能"顺手加固"成抛异常。
- EffectTracker 改动必须保住三个不变式：LIFO、单项失败继续、结束后栈必空。
  对应用例：`test_push_rollback_lifo` / `test_rollback_exception_survival` /
  `test_effect_tracker_rollback_with_all_failing`。
- **v1.1 `push_task` 的额外不变式**：cancel 前必须先 `await sleep(0)`
  让协程进入函数体，否则 finally 不执行（见 ADR 8）。若改回滚顺序，
  回归 `test_push_task_cancels_on_rollback` /
  `test_push_task_awaits_completion` 必须先过。非 Future 入参抛 TypeError
  的防御分支由 `test_push_task_rejects_non_task` 锁死。
- **v1.1.2 已取消任务的不变式**：`push_task` 的 `_cancel_and_await` 必须
  **跳过已取消的任务**。`await` 一个已取消的 Task 会抛回
  `CancelledError`，而 `rollback()` 只捕获 `Exception`
  （`CancelledError` 继承 `BaseException`），异常会逃出整条回滚栈与
  `unload_all`——其余插件永不卸载。回归
  `test_push_task_already_cancelled_keeps_rolling_back` /
  `test_unload_all_survives_cancelled_background_task`。

### lifecycle.py
- 状态机转换表集中在 `enable/disable/unload` 三个方法开头，改转换规则 =
  破坏性变更，先评审。
- 校验（空名/重名/依赖）必须保持在 `load_all` 最前、任何 `plugin.load()`
  之前执行 -- 这是"插件不会观察到半加载状态"的保证。
- **批量原子性（v1.1.1 锁定）**：`load_all`/`enable_all` 失败时按逆
  加载序回滚卸载全部已注册插件，由 `test_load_failure_rolls_back_previous_plugins`
  / `test_enable_failure_rolls_back_all` 锁死。回滚自身的清理失败聚合进
  `RollbackError`（cause 指向原始异常），契约由
  `test_load_failure_rollback_error_aggregates` 锁死；`CancelledError`
  也触发回滚（`test_load_all_rollback_on_cancellation`）。
- **v1.1.2 环报告**：有环时 `_topo_sort` 用 `_find_cycle`（三色 DFS）
  返回真实环路路径，消息形如 `检测到循环依赖: a -> b -> a`。**不要退回
  到列举所有剩余节点**——那会把仅被环拖累的下游插件报成环成员，误导
  排查方向。回归 `test_circular_dependency_error_reports_actual_cycle` /
  `test_circular_dependency_three_node_cycle_path`。
- **v1.2 `load_one`（热插拔）**：依赖只需指向**已加载**插件（不走 `_topo_sort`），
  且失败回滚**只回滚自己**——绝不能改用 `_raise_with_rollback_errors`，那会
  把整台 App 卸掉。锁死用例：`test_load_one_failure_rolls_back_only_new_plugin`、
  `test_load_one_accepts_dependency_already_loaded`、
  `test_load_one_rejects_dependency_not_loaded`。
- **v1.2 `dependents_of`** 是纯查询，供 `App.unload_plugin` 拒绝“卸载还有人
  依赖的插件”。不要把这条守卫下沉进 `LifecycleManager.unload`——批量卸载走
  逆拓扑序，依赖方天然先卸，加进去只会改变冻结方法的错误语义。
- 卸载错误语义：异常聚合抛出但状态推进到 unloaded；`unload_all` 中
  单插件失败不中断其余（`test_unload_all_continues_after_cleanup_failure`
  / `test_unload_all_continues_after_disable_hook_failure`）。若改成
  "失败即中止卸载"，会破坏 `unload_all` 的完整性，属重大变更。

### context.py / app.py
- Context **除 `use` / `use_strict` / `task` 外**全部方法返回 `self`；新增方法
  默认返回 `self` 且不抛业务异常。`task`（v1.1）与 `use_strict`（v1.2）是有意
  例外（分别返回 Task 与“取不到就抛”），见 ADR 9/16，不要“顺手”改成链式。
- **`use()` 的 default 语义是冻结的**（ADR 16）：严格获取一律走 `use_strict`。
  想直接改 `use()` 的，先回去读 maintenance.md 第 6 节与 CHANGELOG 1.2.0。
- **v1.2 ctx 注入**：`load_all` / `load_one` 都在调用 `plugin.load()` 之前写
  `plugin.ctx = ctx`。`Plugin.ctx` 只在 `if TYPE_CHECKING` 块内声明——运行时
  没有这个类属性，因此**不要在契约层运行时 import Context**（会倒置架构 §2 的
  依赖方向）。锁死用例：`test_plugin_ctx_injected_for_all_phases`、
  `test_plugin_ctx_refreshed_after_restart`。
- **v1.2 热插拔**：`App.load_plugin` / `unload_plugin` 都要求 App 已 start；
  `unload_plugin` 在有依赖方时抛 `LifecycleError`（不做级联卸载）。锁死用例：
  `test_app_hot_plug_requires_started_app`、
  `test_app_unload_plugin_refuses_when_depended_on`。
- `config` 切片是引用共享（对 app.config 的修改插件可见）--这是特性不是 bug，
  不要改成拷贝。
- `App.start` 防重入、`stop` 幂等可重启，两条测试
  （`test_app_double_start_raises` / `test_app_restartable`）锁死该行为。
- **v1.1.1 start/stop 错误语义**：start 失败后兜底清空可重试
  （`test_app_start_load_failure_is_recoverable` /
  `test_app_start_enable_failure_is_recoverable`）；stop 的清理兜底与
  `_started` 复位由 try/finally 保证（`test_unload_all_continues_after_cleanup_failure`）。
  不要移除 `start` 的 except 兜底或 `stop` 的 finally——那会让失败后
  的 App 重新不可重启。
- **v1.1 `Context.task` 无事件循环时抛 RuntimeError**（与 bus 协程 handler
  调度语义一致），由 `test_context_task_without_loop_raises` 锁死；不要改成
  隐式建循环，那会让线程归属变模糊。

## 6. 接口变更流程（冻结后）

```
需求提出 -> 影响评估 -> 评审会议 -> 版本标记 -> 文档更新
                ↓
         若涉及破坏性变更:
         1. 标记旧接口 @deprecated
         2. 提供迁移路径
         3. 至少保留 1 个版本周期
```

实操要点：

- **新增**（非破坏）：直接加，同步更新 `core_api.md` 与 `__init__.py` 导出，

**已用的先例（v1.2，P2-2）**：外部评审建议把 `use()` 改成“未注册即抛”，
这属破坏性变更。落地方式是不动 `use()`，**新增** `use_strict()` 作为过渡
接口，并在 `exceptions.py` / `core_api.md` / CHANGELOG 里写明“v1.x 内不收紧
`use()`，留待下一个主版本”。以后遇到同类“想改冻结语义”的需求，照这个模板走。
  补测试。
- **修改签名/语义**（破坏性）：旧路径标注 `@deprecated`（docstring 中写明
  移除版本与迁移方法），新旧并存至少一个版本周期；`core_api.md` 记录
  变更历史。
- **异常类型变更**也算破坏性 -- 调用方的 `except` 列表会失效。
- 每次变更更新 `anima/core/__init__.py` 的 `__version__`
  （语义化：破坏性升主版本）。

## 7. 性能基准维护

`tests/test_core/test_performance.py` 固定了 6 项指标，阈值 = 计划目标值
x 5（CI 抖动保护）。维护规则：

- 改动 bus/effects/lifecycle 的热路径后，本地跑一次基准并对照
  `core_api.md` 的实测表；劣化超过 2 倍必须排查。
- 更新文档时同时更新"实测"列（`pytest -s` 会打印 `[bench]` 行）。
- 不要为提速移除异常隔离 / 幂等性 -- 正确性优先于性能。
- 换机器后基准绝对值会变；阈值是宽松上限，不是竞速目标。

## 8. 常见问题诊断

| 症状 | 原因 | 排查 |
|---|---|---|
| `DependencyError: 检测到循环依赖: a -> b -> a` | 依赖图有环（含自依赖） | 报错串**就是环路路径**，按 `->` 逐个查各插件的 `dependencies` 声明 |
| `LifecycleError: 插件重复注册` | 同名插件同批/跨批注册 | 检查 `Plugin.name` 唯一性 |
| stop 后仍收到事件 | 绕过 `ctx.on` 直接 `bus.subscribe` | 订阅必须经 Context 才有自动回滚 |
| stop 后服务仍存在 | 绕过 `ctx.provide` 直接 `registry.register` | 同上 |
| `use()` 总返回 None | 在 `load()` 阶段调用（依赖可能未加载） | 移到 `enable()` 阶段 |
| `RollbackError` 但状态正常 | cleanup 抛异常（已聚合不中断） | 读 `.errors` 逐个看子异常 |
| 协程 handler 没执行 | 同步 `emit` 时无运行中的事件循环 | 用 `emit_async` 或在 async 上下文中 emit |
| enable 报非法转换 | 插件未加载或已 enabled | 先 `get_state(name)` 确认状态机位置 |

## 9. 提交与版本约定

- 按里程碑提交（对照 Phase 1-4 的粒度）；一个 commit 一件事。
- message 格式：`feat(core)/fix(core)/docs/test/chore: 摘要` + 正文说明动机。
- 版本号在 `anima/core/__init__.py`：破坏性 -> 主版本，新增 -> 次版本，
  修复 -> 补丁版本。
- 发布前 checklist：全量测试绿 / 覆盖率达标 / 铁律检查通过 /
  `core_api.md` 与代码签名一致 / 基准表更新。

## 10. 写一个新插件（给业务开发者）

```python
from anima.core import Plugin, Context

class MyFeature(Plugin):
    name = "my-feature"
    version = "1.0.0"
    dependencies = []          # 依赖其他插件时填其 name

    async def load(self, ctx: Context) -> None:
        # 只注册自己；不要 ctx.use() 别人
        ctx.provide("my.api", self)
        ctx.on("app.ready", self._on_ready)
        ctx.on_cleanup(self._close_file)   # 自定义清理，LIFO 执行

    async def enable(self) -> None:
        db = self.ctx.use_strict("db")           # 依赖已就绪；缺失即抛，便于排错
        ...

    async def disable(self) -> None: ...   # 停止对外活动
    async def unload(self) -> None: ...    # 框架已回滚订阅/服务
```

记住三条：副作用一律经 `ctx.on/ctx.provide/ctx.on_cleanup` 登记；
`use()` 只在 `enable` 及之后；不要在插件里持有 bus/registry 引用。

## 11. 日志约定（v1.1.2）

- 内核日志一律走 `anima/core/log.py` 的 `logger`（名字 `anima`），
  子模块用 `logger.getChild("<模块名>")` 派生（当前只有 `anima.bus`）。
- 内核**不加 handler、不设级别** -- 把配置权留给应用。调试时：

  ```python
  import logging
  logging.getLogger("anima").setLevel(logging.DEBUG)
  ```

- 当前唯一的日志点：`EventBus._report`（handler 异常上报）。加新日志点
  前先问"这是不是本来就该用异常上报"——`RollbackError.errors` 这类
  诊断必须留在异常里，调用方要拿它，别把异常语义稀释成日志。
- 不要在 `core/` 里 `logging.basicConfig(...)`：库不得接管应用的日志配置。
