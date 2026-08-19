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
anima/core/            内核（735 行，纯标准库，接口已冻结）
  app.py               组装器：start/stop、effects 持有者
  bus.py               事件总线：_exact dict + _wild 列表
  registry.py          服务注册表
  lifecycle.py         校验 + Kahn 排序 + 状态机 + 卸载（最复杂，改动最谨慎）
  context.py           插件上下文（链式 API）
  effects.py           LIFO 副作用栈
  plugin.py            插件 ABC
  exceptions.py        异常体系
tests/test_core/       104 个测试，12 个文件，按被测模块命名
  conftest.py          bus/registry/effects/app fixtures + RecorderPlugin
  test_performance.py  性能基准（阈值 = 目标值 x5 安全系数）
  test_edge_cases.py   边界 + 压力
docs/                  architecture / core_api / maintenance 三份文档
check_kernel_rules.py  铁律检查（行数 <1000、无第三方 import）
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
8. `core/` 总行数 < 1000。加功能前先想能不能放到 `anima/plugins/` 或
   `anima/utils/` -- 默认答案通常是"能"。

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
- 新增订阅结构时同步维护 `count()`/`clear()`，`App.stop` 的"bus 为空"
  验收依赖 `count()` 正确。
- emit 的异常隔离必须保持：改 handler 调度时先读 `test_handler_exception_isolation`。

### registry.py / effects.py
- `use()` 返回 default、`unregister` 幂等，这两个语义被 Context 与自动回滚
  依赖，不能"顺手加固"成抛异常。
- EffectTracker 改动必须保住三个不变式：LIFO、单项失败继续、结束后栈必空。
  对应用例：`test_push_rollback_lifo` / `test_rollback_exception_survival` /
  `test_effect_tracker_rollback_with_all_failing`。

### lifecycle.py
- 状态机转换表集中在 `enable/disable/unload` 三个方法开头，改转换规则 =
  破坏性变更，先评审。
- 校验（空名/重名/依赖）必须保持在 `load_all` 最前、任何 `plugin.load()`
  之前执行 -- 这是"插件不会观察到半加载状态"的保证。
- 卸载错误语义：异常聚合抛出但状态推进到 unloaded。若要改成"失败即中止
  卸载"，会破坏 `unload_all` 的完整性，属重大变更。

### context.py / app.py
- Context 全部方法返回 `self`；新增方法同样返回 `self` 且不抛业务异常。
- `config` 切片是引用共享（对 app.config 的修改插件可见）--这是特性不是 bug，
  不要改成拷贝。
- `App.start` 防重入、`stop` 幂等可重启，两条测试
  （`test_app_double_start_raises` / `test_app_restartable`）锁死该行为。

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
| `DependencyError: 检测到循环依赖` | 依赖图有环（含自依赖） | 检查各插件 `dependencies` 声明 |
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
        db = self._ctx.use("db")           # 依赖已就绪
        ...

    async def disable(self) -> None: ...   # 停止对外活动
    async def unload(self) -> None: ...    # 框架已回滚订阅/服务
```

记住三条：副作用一律经 `ctx.on/ctx.provide/ctx.on_cleanup` 登记；
`use()` 只在 `enable` 及之后；不要在插件里持有 bus/registry 引用。
