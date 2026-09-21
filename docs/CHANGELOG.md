# 变更记录

所有显著变更记录于此文件。版本号遵循语义化版本规范；内核公共接口自
v1.0 起冻结，任何破坏性变更需走 `maintenance.md` 第 6 节的评审流程。

## [1.1.2] — 2026-09-08

按外部评审的 P0/P1 清单修复正确性缺陷，并补上两项 P4 级工程化能力。
公共签名**仅新增**（`EventBus.__init__` 增加可选参数、新增 `ErrorHook`
与 `EventBus.set_error_hook`）；两处行为增强（`dependencies` 默认值、
循环依赖报错文本）不触及既有调用契约，无破坏性变更。

### 修复

- **循环依赖报错只列真实环路（P0-5）**：`_topo_sort` 判定有环后改用
  三色 DFS 回溯真实环路。消息从"涉及插件: a, b, downstream"（把仅被环
  拖累的下游插件也报成环成员，误导排查方向）变为
  "检测到循环依赖: a -> b -> a"。
- **`dependencies` 默认值改为不可变元组（P0-1）**：`Plugin.dependencies`
  由 `list[str] = []` 改为 `ClassVar[Sequence[str]] = ()`。旧默认值是
  **类属性**，所有子类共享同一个 list，任何
  `self.dependencies.append(...)` 都会污染全局；元组默认值从根上消除
  这类静默 bug。子类照旧可赋值 list 或 tuple。
- **`disable()` 文档与实现对齐（P0-2）**：`plugin.py` 与
  `architecture.md` §4.2 原称"disable 时框架自动回滚副作用"，但
  `LifecycleManager.disable()` 只调用钩子、**不回滚**——订阅与注册会
  一直保留到 `unload()`。按**实现**修正文档（不改语义），并写明分工：
  disable 停止"主动做事"，unload 才卸下"向内注册"的东西。
- **`Context.config` 容忍非字典配置（P0-3）**：`app.config["plugins"]`
  为 `None`（如 YAML 空节）时，原先在构造 Context 时抛
  `AttributeError`；现按"缺省即空 dict"归一化。
- **已取消的后台任务不再打断卸载（P1-4，实际严重度 P0）**：
  `EffectTracker.push_task` 登记的任务若在回滚前已被取消，回滚中的
  `await task` 会抛回 `CancelledError`；`rollback()` 只捕获
  `Exception`，而 `CancelledError` 继承 `BaseException`，异常会一路
  逃出 `unload_all`——**整条卸载链中断，其余插件永不卸载**。现在已取消
  的任务直接跳过（视为正常收尾），其余已结束任务照旧 re-raise 进
  `RollbackError` 聚合。
- **拓扑排序改用 deque（P0-4）**：Kahn 排序的 `list.pop(0)` 是 O(n)，
  改为 `collections.deque.popleft()`。

### 新增

- **`EventBus(on_error=...)` / `EventBus.set_error_hook(hook)`（P1-1）**：
  handler 异常依旧**隔离**（不上抛给发布方，架构 §5.2 语义不变），但不再
  无声——交给 `ErrorHook = Callable[[str, Handler, BaseException], None]`
  上报；未提供钩子时默认写 `anima.bus` logger。**上报动作本身也遵守
  异常隔离**：钩子自己抛异常时退回默认 logger，绝不让异常从 `emit` 漏出。
- **`anima/core/log.py`（P4-3）**：内核统一日志出口
  `logging.getLogger("anima")`，子模块用 `getChild` 派生（如
  `anima.bus`）。遵循标准库库作者约定：不加 handler、不设级别，配置权
  留给应用。
- **`anima/py.typed` + `[tool.setuptools.package-data]`（P4-1）**：
  PEP 561 标记，mypy / pyright 开始读取本包内联注解。
- **`ErrorHook` 从 `anima.core` 导出**。

### 其他

- `pyproject.toml` 的 `version` 由 `1.0.0` 修正为 `1.1.2`（此前长期与
  `anima.core.__version__` 不一致）。

### 文档

- `architecture.md`：§4.2 disable 语义修正、§4.3 总线异常上报、§5.2 异常
  策略表补行、ADR 12/13/14、§10 演进表更新。
- `core_api.md`：`Plugin.dependencies` 新签名、`EventBus` 错误钩子、
  日志出口、变更记录。
- `maintenance.md`：模块地图与行数、bus/effects/plugin 逐模块不变式与
  锁定测试名、新增日志约定一节。
- `README.md`：版本、规模、测试数与本版要点。

### 验收

- 规模 841 -> **961 行**（目标 <1000，余量 39 行）
- 测试 123 -> **136 个**（+13：bus 错误钩子 6、lifecycle 环报告 3、
  context 配置边界 2、plugin 不可变默认值 1、effects 已取消任务 1）
- 覆盖率 **99%** 不变（lifecycle 98%；未覆盖 3 行仍是 v1.0 起的历史缺口）
- `check_kernel_rules.py` 通过：纯标准库、无第三方 import
- 新增用例已做"回退源码"验证：12 个新用例在 v1.1.1 基线上 11 个失败，
  第 12 个（`test_context_config_replaces_non_dict_section`）守护的是
  v1.1.1 就已存在的分支

> ⚠️ **行数余量告警**：内核从 841 行升到 961 行，余量由 159 行降到
> 39 行。评审清单里剩余 P2/P3 项（事件优先级、`emit_collect`、生命周期
> 事件、单插件热插拔、服务接口校验等）合计约 90 行，**直接实施会突破
> 1000 行铁律**。动手前必须先决策：精简 docstring、把非内核关注点移到
> `anima/utils/`，或正式上调行数上限。

## [1.1.1] — 2026-08-21

三项缺陷修复（公共签名不变；批量操作的**错误时行为**有语义增强，
属容错方向修复，原行为是缺陷）：

### 修复

- **`load_all` / `enable_all` 原子性**：某插件的 `load()` 或
  `enable()` 抛异常时，此前已注册的全部插件（含失败者自身的部分
  副作用）按**逆加载序**尽力卸载，不留半加载状态。此前行为是残留
  内部状态且 `App.stop()` 因 `_started=False` 无法清理、再次
  `start()` 抛"插件重复注册"。
- **回滚自身的异常契约**：load/enable 失败触发的回滚若清理也失败，
  抛聚合 `RollbackError`（`__cause__` 指向原始异常，`errors` 只含
  清理失败项）；回滚干净时原样重抛原始异常（含 `CancelledError`）。
- **`unload_all` 聚合语义**：单个插件的清理失败不再中断其余插件
  卸载（原行为是遇第一个 `RollbackError` 即中止，剩余插件永不
  卸载）；失败聚合后统一抛出。
- **`App.stop()` 兜底**：卸载异常不再跳过 bus/registry/_effects
  清理与 `_started` 复位（try/finally 保证），App 始终可重启。
  `App.start()` 失败后同样兜底清空，可再次 `start()`。
- **`bus.py` 移除通配 handler 的死排序**：`_wild_matches` 原对
  通配 handler 做 sync-before-async 排序而精确 handler 不排序，
  但该排序在行为上不可观察（异步 handler 从不内联执行、稳定排序
  不改组内注册序），属死代码。同时把真实顺序契约写入 docstring
  并以 `test_handler_order_contract` 锁死：**精确 handler 先于
  通配 handler，组内按注册顺序**。
- **`context.py` 注解修正**：`effects` 字段的
  `"anima.core.effects.EffectTracker"` 全限定路径字符串改为运行时
  导入 + 裸注解（`context.py` 本就运行时导入该模块，无循环导入）。
  该条注解在 `typing.get_type_hints` 下由必然 NameError 变为可解析。

### 文档

- `architecture.md`：§4.8 start/stop 失败语义、§5.2 异常策略表
  补两行、§6.2 stop 流程图、ADR 10/11、§10 演进表措辞修正。
- `core_api.md`：start/stop 与批量生命周期方法的错误语义、总线
  顺序契约、变更记录。
- `maintenance.md`：lifecycle/app/bus 逐模块不变式与锁定测试名。

### 验收

- 规模 785 -> **841 行**（目标 <1000）
- 测试 113 -> **123 个**（+10：批量原子性 8 + 顺序契约 1 +
  disable 钩子失败聚合 1）
- 覆盖率 **99%** 不变（lifecycle 98%，未覆盖 3 行为 v1.0 起的
  历史缺口：unload 前的防御性状态检查与同步 unload 钩子异常路径）
- `check_kernel_rules.py` 通过：纯标准库、无第三方 import

## [1.1.0] — 2026-08-19

依据 AnimaPet 迁移计划 TD2 决策表，**仅新增接口**，v1.0 公共签名与
语义不变（非破坏性变更）。

### 新增

- **`EffectTracker.push_task(task)`**：后台任务纳入 LIFO 回滚栈，卸载时
  取消并等待真正结束。关键实现：cancel 前先 `await sleep(0)` 让协程进入
  函数体，保证 finally 执行（见 architecture.md ADR 8）。非 Future 入参
  抛 `TypeError`。
- **`Context.task(coro)`**：插件后台任务入口，等价
  `push_task(asyncio.ensure_future(coro))`；返回 Task 本身，是 Context 上
  唯一不返回 `self` 的方法（见 ADR 9）。需要运行中的事件循环，无循环时
  抛 `RuntimeError`。
- **`bus.py` 线程语义文档化**：在模块 docstring 明确"跨线程同步 emit 安全、
  handler 在调用方线程执行、订阅约定只发生在内核线程"。无代码改动。

### 文档

- `architecture.md` 第 5.1 节加后台任务调用点、第 5.3 节加 push_task
  回滚语义、第 7 节重写并发模型（正式线程结论）、ADR 加第 8/9 条、
  演进表加类型形式 provide/use。
- `core_api.md` 更新 effects/context 签名、性能基准表更新、加变更记录节。
- `maintenance.md` 逐模块注意事项补 push_task/task 的不变式与锁死测试名。

### 验收

- 规模 735 → **785 行**（目标 <1000）
- 测试 104 → **113 个**（+9 个 v1.1 用例）
- 覆盖率 **99%** 不变（各模块 ≥97%；effects 98%，未覆盖为防御性分支已补测试达 100%）
- 性能与 v1.0 基准一致（emit 3.1µs、排序 0.13ms、生命周期 2.2ms、回滚 1.3ms、空 App 1.1KiB）
- `check_kernel_rules.py` 通过：纯标准库、无第三方 import

## [1.0.0] — 2026-08-18

初始冻结版本。9 个模块 735 行，104 个测试，覆盖率 99%。详见
`core_api.md` 与 `architecture.md`。
