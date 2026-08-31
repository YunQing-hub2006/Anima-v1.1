# Anima 内核开发会话 · 工作交接记录

> **会话日期**: 2026-08-18 ~ 2026-08-19
> **产出位置**: `E:\Zcode-work\Anima-v1.1`（v1.1 已完成）
> **上游基线**: `E:\Zcode-work\work`（Anima 内核 v1.0，**冻结只读，不得改动**）
> **v1.1 状态**: ✅ 已完成并提交（commit `988ae8c`），113 测试全绿，覆盖率 99%

---

## 一、本次会话做了什么

### 1.1 完成的工作

按《Anima 内核开发计划》（两份 .txt 原始规划）从零实现并冻结了 Anima
内核 **v1.0**（仓库 `E:\Zcode-work\work`），随后在本目录 `Anima-v1.1`
完成 **v1.1 升级**。两轮工作均在各自仓库按里程碑提交 git。

**v1.0 规模与质量**（work/ 仓库，冻结基线）：
- `anima/core/` 共 9 个模块、**735 行**（目标 <1000）
- **纯标准库**（`check_kernel_rules.py` 自动校验）
- **104 个测试全部通过**，总覆盖率 **99%**

**v1.1 升级**（本目录，依据 AnimaPet/PLAN.md TD2 决策表，仅新增非破坏）：
- 新增 `EffectTracker.push_task(task)` + `Context.task(coro)`：后台任务
  纳入 LIFO 回滚栈，卸载时取消并等待真正结束（cancel 前先 `sleep(0)`
  保证协程体执行 finally，见 architecture.md ADR 8）
- `bus.py` 模块 docstring 明确线程语义（无代码改动）
- 规模 735 → **785 行**；测试 104 → **113 个**；覆盖率 **99%** 不变
- 四份文档全部更新：core_api（签名+变更记录）、architecture（ADR 8/9
  +第 7 节并发模型重写）、maintenance（逐模块不变式）、新增 CHANGELOG

### 1.2 后续衍生任务

`E:\Zcode-work\AnimaPet` 是桌面宠物元框架，消费 v1.1 内核。迁移计划见
`E:\Zcode-work\AnimaPet\PLAN.md`，其中 **TD1**（Qt 主线程 + 内核 asyncio
后台线程的桥接方案）和 **TD2**（本次 v1.1 升级）已在此完成。AnimaPet
的 Phase 0 第 2 条（内核 v1.1 升级）现已打勾，可进入 Phase 1。

---

## 二、仓库与文件地图

### 2.1 当前目录 `E:\Zcode-work\Anima-v1.1`

```
Anima-v1.1/
├── HANDOVER.md            ← 本文件（工作交接记录，v1.1 已标记完成）
├── anima/core/            ← 9 个模块，785 行（v1.1 冻结）
├── tests/test_core/       ← 12 个测试文件，113 个测试
├── docs/
│   ├── CHANGELOG.md       ← v1.1 变更记录（新增）
│   ├── architecture.md    ← 含 ADR 8/9、第 7 节并发模型
│   ├── core_api.md        ← 含 push_task/task 签名与变更记录节
│   └── maintenance.md     ← 含 v1.1 逐模块不变式
├── pyproject.toml         ← pytest asyncio_mode=auto
├── check_kernel_rules.py  ← 行数<1000 + 无第三方 import 校验
├── README.md              ← v1.1 头部
└── .gitignore
```

### 2.2 关键外部目录

| 路径 | 角色 | 状态 |
|---|---|---|
| `E:\Zcode-work\work` | 内核 v1.0 上游、冻结基线 | **只读** |
| `E:\Zcode-work\Anima-v1.1` | 内核 v1.1（本目录） | ✅ 完成 |
| `E:\Zcode-work\AnimaPet` | 桌面宠物元框架（消费 v1.1） | 待启动 |
| `E:\dsh-work\YingPet-v4` | 迁移源代码 | 只读参考 |

### 2.3 git 历史

```
988ae8c feat(core): v1.1 - Context.task/push_task 后台任务卸载 + 线程语义文档
cdb502e chore: 从 work/ v1.0 基线 fork v1.1 工作目录
```

---

## 三、v1.1 已完成的工作（原 TODO 清单的执行结果）

依据 `AnimaPet/PLAN.md` 的 **TD2 决策表**，三块内容均已完成：

### 3.1 ✅ `EffectTracker.push_task` + `Context.task`（核心新增）

**实现**：
- `anima/core/effects.py` 新增 `push_task(task: asyncio.Future) -> asyncio.Future`
  - 把一个 async cleanup `_cancel_and_await` push 进栈：先 `await sleep(0)`
    让协程进入函数体（否则 cancel 落在未启动协程上、finally 不执行），
    再 `task.cancel()` + `await task`（`suppress(CancelledError)`）
  - 已完成任务登记后 rollback 会 re-raise 其异常（进入 RollbackError 聚合）
  - 非 Future 入参抛 `TypeError`（防御）
- `anima/core/context.py` 新增 `task(coro: Coroutine) -> asyncio.Task`
  - `asyncio.ensure_future(coro)` + `self.effects.push_task(task)`，返回 Task
  - 唯一不返回 `self` 的 Context 方法（ADR 9）
  - 无运行循环抛 `RuntimeError`（与 bus 协程 handler 语义一致）
- `lifecycle.py` 无改动：push_task 走与 push 相同的 rollback 栈，LIFO 与
  异常聚合自动复用

**新增测试**（9 个，分布在 test_effects.py 与 test_context.py）：
- `test_push_task_cancels_on_rollback` / `test_push_task_awaits_completion`
- `test_push_task_exception_isolated` / `test_push_task_already_done`
- `test_push_task_lifo_with_plain_push` / `test_push_task_rejects_non_task`
- `test_context_task_returns_task` / `test_context_task_cancelled_on_unload`
- `test_context_task_without_loop_raises`

### 3.2 ✅ EventBus 线程语义文档化

`bus.py` 模块 docstring 加"线程语义"节：跨线程同步 emit 安全、handler 在
调用方线程执行、订阅约定只发生在内核线程。`architecture.md` 第 7 节
重写为正式并发结论。**无代码改动**。

### 3.3 ✅ 类型形式 provide/use（登记不实现）

`architecture.md` 演进表加"类型形式 provide/use"，标注由框架层（AnimaPet）
封装、不进内核。core_api.md 变更记录节也登记。

---

## 四、验收结果

```
113 passed in 0.53s
Name                  Stmts  Miss  Cover
anima\core\__init__.py    10     0   100%
anima\core\app.py         39     0   100%
anima\core\bus.py         73     0   100%
anima\core\context.py     38     0   100%
anima\core\effects.py     52     0   100%
anima\core\exceptions.py  17     0   100%
anima\core\lifecycle.py  114     3    97%
anima\core\plugin.py      13     0   100%
anima\core\registry.py    21     0   100%
TOTAL                    377     3    99%

TOTAL 行数 785 (<1000 目标)
import 检查: 全部为标准库 / anima 自身
```

性能与 v1.0 基准一致：emit 3.1µs、排序 0.13ms、生命周期 2.2ms、
回滚 1.3ms、空 App 1.1KiB。

---

## 五、关键设计约束（不可违反）

1. **work/ 仓库冻结只读**——v1.1 的所有改动只在 Anima-v1.1 目录。
2. **仅新增，非破坏性**——v1.0 公共接口签名/语义未变。
3. **纯标准库**——`contextlib`/`asyncio` 均为标准库。
4. **<1000 行**——785 行，余量充足。
5. **异常隔离不变式**——task cancel 抛异常不阻断其他回滚
   （`suppress(CancelledError)` + RollbackError 聚合）。
6. **LIFO 顺序**——push_task 与普通 push 同栈。
7. **push_task 不变式**——cancel 前先 `sleep(0)`（ADR 8），改回滚顺序
   必须先过 `test_push_task_cancels_on_rollback`。

---

## 六、环境与复跑命令

```bash
# 独立 venv（不复用 work/.venv）
E:\Zcode-work\Anima-v1.1\.venv\Scripts\python.exe -V   # Python 3.13.0

# 全量测试 + 覆盖率 + 铁律检查
.venv\Scripts\python -m pytest tests/test_core/ -v
.venv\Scripts\python -m pytest tests/test_core/ --cov=anima.core --cov-report=term
.venv\Scripts\python check_kernel_rules.py
```

---

## 七、参考文档索引

- 变更记录：`docs/CHANGELOG.md`（v1.1 详述）
- 内核架构设计：`docs/architecture.md`（ADR 8/9、并发模型第 7 节）
- 接口签名：`docs/core_api.md`（v1.1 全部公共 API + 变更记录节）
- 开发维护指南：`docs/maintenance.md`（v1.1 逐模块不变式）
- 桌面宠物迁移计划：`E:\Zcode-work\AnimaPet\PLAN.md`（TD1/TD2 决策来源）
- 原始规划书：`E:\Zcode-work\work\` 下两份 .txt

> v1.1 内核开发已完成。后续工作转向 AnimaPet 迁移，从 PLAN.md 的
> Phase 1（最小可运行宠物）开始——内核上游指向本目录
> `E:\Zcode-work\Anima-v1.1`。

---

## 二、仓库与文件地图

### 2.1 当前目录 `E:\Zcode-work\Anima-v1.1`

```
Anima-v1.1/
├── HANDOVER.md            ← 本文件（工作交接记录）
└── stage/                 ← 从 work/ git archive HEAD 提取的 v1.0 基线
    ├── anima/core/        ← 9 个模块，735 行（待升级到 v1.1）
    ├── tests/test_core/   ← 12 个测试文件，104 个测试
    ├── docs/              ← architecture.md / core_api.md / maintenance.md
    ├── pyproject.toml     ← pytest asyncio_mode=auto 配置
    ├── check_kernel_rules.py  ← 行数<1000 + 无第三方 import 校验
    ├── README.md
    └── .gitignore
```

`stage/` 是 v1.0 的**干净快照**（git archive 不含 .venv / __pycache__ /
.git），可直接作为 v1.1 开发的起点。**尚未初始化 git**，也**尚未建 venv**
（见第三节 TODO 第 1-2 条）。

### 2.2 关键外部目录

| 路径 | 角色 | 状态约定 |
|---|---|---|
| `E:\Zcode-work\work` | 内核 v1.0 上游、冻结基线 | **只读，禁止改动** |
| `E:\Zcode-work\Anima-v1.1` | 内核 v1.1 工作目录（本目录） | 本次新建，待开发 |
| `E:\Zcode-work\AnimaPet` | 桌面宠物元框架（消费 v1.1） | 已有 PLAN.md，待启动 |
| `E:\dsh-work\YingPet-v4` | 迁移源代码 | 只读参考 |
| `E:\Zcode-work\work\.venv` | v1.0 用的 Python 3.13 venv | 已装 pytest 系；v1.1 应建独立 venv |

---

## 三、待办：v1.1 升级清单（接手者从这里开始）

依据 `AnimaPet/PLAN.md` 的 **TD2 决策表**，v1.1 相对 v1.0 仅**新增**
接口（非破坏性变更），走 maintenance.md 的冻结变更流程。具体三块：

### 3.1 `EffectTracker.push_task` + `Context.task`（核心新增）

**需求来源**：规划书 §2.2.2 与 §6.1——插件通过 `ctx.task(coro)` 创建
后台任务，卸载时自动 `cancel`。v1.0 的 EffectTracker 只能 push 同步/
异步 cleanup 函数，不能把"正在运行的 Task"纳入回滚栈。

**实现要点**（已与 v1.0 设计对齐，不破坏既有语义）：
1. `anima/core/effects.py`：新增
   ```python
   def push_task(self, task: asyncio.Task) -> asyncio.Task
   ```
   - 把 `task.cancel` 作为 cleanup push 进栈（注意：`Task.cancel` 是
     协程方法，`rollback` 已支持异步 cleanup，但 cancel 返回的协程需要
     被 await 才真正取消——需在 rollback 里 `await` 它，或用
     `lambda: task.cancel()` 让 cancel 的协程由 EffectTracker 调度）。
   - **关键细节**：`task.cancel()` 本身返回一个协程但不 await 也能
     触发取消请求；为干净起见，push 一个 async cleanup：
     ```python
     async def _cancel():
         task.cancel()
         with contextlib.suppress(BaseException):
             await task
     self.push(_cancel)
     ```
     这样回滚时真正等待任务结束，避免悬挂。
2. `anima/core/context.py`：新增
   ```python
   def task(self, coro: Coroutine) -> asyncio.Task
   ```
   - 通过 `asyncio.ensure_future(coro)` 创建 Task（需要运行中的事件
     循环；无循环时报 `RuntimeError`——与 v1.0 bus 的协程调度语义一致，
     不做隐式建循环）。
   - 调用 `self.effects.push_task(task)` 登记回滚。
   - 返回 `self` 不合适（要返回 Task 给调用方），所以 `task` 是 Context
     上**唯一不返回 self 的方法**——在 docstring 与 core_api.md 显式
     标注，避免与链式 API 约定混淆。
3. `anima/core/lifecycle.py`：unload 路径**无需改动**——push_task
   登记的 cleanup 走的是与 push 相同的 rollback 栈，LIFO 与异常聚合
   语义自动复用。但需测试覆盖"卸载时正在运行的 task 被 cancel 且
   await 完成"。

**验收测试清单**（新增到 `tests/test_core/test_effects.py` 与
`test_context.py`，共约 7 个）：
- `test_push_task_cancels_on_rollback`：push 一个长任务，rollback 后
  task 状态为 cancelled
- `test_push_task_awaits_completion`：rollback 等待任务真正结束而非
  仅发 cancel
- `test_push_task_exception_isolated`：task 抛异常不阻断其他回滚
- `async test_context_task_registered`：ctx.task 创建的 task 在
  effects 栈中
- `async test_context_task_cancelled_on_unload`：插件 unload 后其
  task 被 cancel
- `async test_context_task_returns_task`：返回值是 asyncio.Task
- `async test_context_task_without_loop_raises`：无运行循环时报
  RuntimeError（与 bus 一致）

### 3.2 EventBus 线程语义文档化（无代码改动）

v1.0 的 EventBus 数据结构是普通 dict/list，未加锁。在 AnimaPet 的
TD1 决策下（内核 asyncio 跑后台线程、Qt 占主线程），同步 `bus.emit`
会被 Qt 线程跨线程调用。**结论已定**：单写多读、无 await 临界区，
跨线程同步 emit 安全；但需在 `bus.py` 模块 docstring 与
`docs/architecture.md` 第 7 节明确写出这一结论与边界，避免后人误加锁
或误用。**不改任何代码**，只补文档。

### 3.3 类型形式 provide/use（不进内核）

规划书 §6.3 提到 `ctx.provide(ConfigService, self)` / `ctx.use(ConfigService)`
的类型安全形式。**决策**：内核不动，由 AnimaPet 的插件层薄封装
（类 → `f"{cls.__module__}.{cls.__qualname__}"` 字符串键）。v1.1 文档
里只需在 core_api.md 的"演进方向"登记此项，不实现。

---

## 四、执行步骤（建议顺序）

1. **初始化 Anima-v1.1 仓库**：
   - 把 `stage/` 内容移到 `Anima-v1.1/` 根（`move stage\* .` 或直接
     在 stage 下开发——建议前者，根目录更干净）
   - `git init`、首次 commit `chore: 从 work/ v1.0 基线 fork v1.1 工作目录`
2. **建独立 venv 并装工具链**：
   - `python -m venv .venv`（基础 Python 3.13，**不复用 work/.venv**）
   - `.venv\Scripts\python -m pip install pytest pytest-asyncio pytest-cov`
   - 冒烟：`.venv\Scripts\python -m pytest tests/test_core/ -v` 应 104 全绿
3. **实现 3.1**：改 effects.py + context.py，先写 7 个新测试再改实现
4. **更新文档**：`__init__.py` 的 `__version__ = "1.1.0"`；core_api.md
   补 `push_task`/`task` 签名；architecture.md 第 7 节补线程语义；
   maintenance.md 在"逐模块修改注意事项"补 push_task 的不变式；
   新增 `docs/CHANGELOG.md` 记 v1.1 变更
5. **验收**：全量 pytest + 覆盖率（仍 ≥97%）+ `check_kernel_rules.py`
   （行数会略增但应仍 <1000；若超需精简）
6. **提交**：`feat(core): v1.1 - Context.task/push_task 后台任务卸载 + 线程语义文档`
7. **回填 AnimaPet/PLAN.md**：把 P0 的 v1.1 升级项打勾，并在
   "立即行动"里把上游指向 `E:\Zcode-work\Anima-v1.1`

---

## 五、关键设计约束（不可违反）

1. **work/ 仓库冻结只读**——v1.1 的所有改动只在 Anima-v1.1 目录，
   不回写 work/。
2. **仅新增，非破坏性**——v1.0 的任何公共接口签名/语义不得变更
   （maintenance.md 第 6 节的冻结流程）。`push_task`/`task` 是纯新增。
3. **纯标准库**——core/ 的 import 白名单由 `check_kernel_rules.py`
   拦截；`contextlib` 是标准库，3.1 用到的 `suppress` 没问题。
4. **<1000 行**——v1.0 是 735 行，新增 push_task/task 预估 +30~40 行，
   仍远低于上限。
5. **异常隔离不变式**——task cancel 抛异常不得阻断其他回滚
   （`suppress(BaseException)` 兜底）。
6. **LIFO 顺序**——push_task 登记的 cleanup 与普通 push 走同一栈，
   后创建的 task 先被 cancel。
7. **测试先行**——每个新分支必须有对应用例，模块覆盖率保持 ≥90%。

---

## 六、环境与复跑命令

```bash
# 基础 Python（work/.venv 是 3.13，复用同一个基础解释器）
C:\Users\Zhang\AppData\Local\Programs\Python\Python313\python.exe -V

# v1.0 基线复跑（在 work/ 或本目录 stage/ 都可）
.venv\Scripts\python -m pytest tests/test_core/ -v
.venv\Scripts\python -m pytest tests/test_core/ --cov=anima.core --cov-report=term
.venv\Scripts\python check_kernel_rules.py
```

---

## 七、参考文档索引

- 内核架构设计：`docs/architecture.md`（含 ADR 决策记录、并发模型、演进方向）
- 接口签名：`docs/core_api.md`（v1.0 全部公共 API + 性能基准表）
- 开发维护指南：`docs/maintenance.md`（铁律、变更流程、逐模块注意事项）
- 桌面宠物迁移计划：`E:\Zcode-work\AnimaPet\PLAN.md`（TD1/TD2 决策来源）
- 原始规划书：`E:\Zcode-work\work\` 下两份 .txt（内核开发计划）

> 接手者从第三节 TODO 开始即可；有疑问先查 architecture.md 的 ADR 与
> maintenance.md 的逐模块注意事项，再查 PLAN.md 的 TD 决策表。
