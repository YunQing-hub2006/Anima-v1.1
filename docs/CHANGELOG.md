# 变更记录

所有显著变更记录于此文件。版本号遵循语义化版本规范；内核公共接口自
v1.0 起冻结，任何破坏性变更需走 `maintenance.md` 第 6 节的评审流程。

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
