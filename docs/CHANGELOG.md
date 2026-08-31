# 变更记录

所有显著变更记录于此文件。版本号遵循语义化版本规范；内核公共接口自
v1.0 起冻结，任何破坏性变更需走 `maintenance.md` 第 6 节的评审流程。

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
