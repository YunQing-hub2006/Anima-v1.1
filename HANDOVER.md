# Anima 内核开发会话 · 工作交接记录

> **会话日期**：2026-09-08
> **产出位置**：`E:\Zcode-work\Anima-v1.1`（内核）
> **本次范围**：v1.1.2 → v1.2.0 → v1.3.0 → v1.3.1，外加下游 `AnimaPet` 内嵌内核与测试同步
> **上游基线**：`E:\Zcode-work\work`（v1.0，**冻结只读**）
> **状态**：三个里程碑均已提交并推送到 `origin/master`，工作区干净

---

## 一、一句话结论

内核从 v1.1.1 推进到 **v1.3.0**：修掉 5 个 P0 级正确性缺陷，补齐异常可观测性、
总线线程安全、插件易用性与编排能力；下游 `AnimaPet` 的内嵌内核已同步到
v1.3.0 并通过全部 268 个测试。**内核侧无遗留待办**，唯一需要提前决策的是
规模预算（见 §5.1）。

---

## 二、本次会话做了什么

### 2.1 三个里程碑

| 版本 | commit | 主题 |
|---|---|---|
| v1.1.2 | `b3c65df` | P0 正确性修复 + handler 异常上报 + 日志出口 |
| v1.2.0 | `a90e190` | 总线加锁、`Plugin.ctx` 注入、`use_strict`、单插件热插拔 |
| v1.3.0 | `86245dc` | 事件优先级、`emit_collect`、生命周期事件、`config_defaults`、接口校验、非内核自动发现 |
| v1.3.1 | （本次提交，见 `git log -1`） | `ctx` 明确为保留属性名 + 注入失败给可操作报错 |

- 输入是一份外部评审的 **P0→P4 清单**，逐条核对后确认 P0 全部属实（§2.2）
- `origin/master` 已更新到 `86245dc`。本地分支叫 `AnimaV1.2`，远程主线是
  `master`，属**快进推送**（无 force）
- 逐版本细节见 `docs/CHANGELOG.md`；本文件只记"为什么"和"坑"

### 2.2 评审清单的核对结果（清单本身有 4 处要修正）

- **P0-1 ~ P0-5 全部属实**：`dependencies` 可变类属性被所有子类共享、
  `disable` 文档与实现不一致、`Context.config` 遇 `None` 崩、Kahn 用了
  `list.pop(0)`、环报错把"被环拖累"的插件也算成环成员。
- **P1-4 实际是 P0 严重度**：已取消的后台任务会让 `rollback()` 抛出的
  `CancelledError` 逃出 `unload_all`，**其余插件永不卸载**。
- **P1-2（总线加锁）与仓库既有结论冲突**：`architecture.md` §7 写的是
  "无锁、避免后人误加锁"。落地时把它改写成 **ADR 15**，而不是悄悄改代码
  ——结论可以推翻，但必须写清为什么推翻。
- **P2-2 是破坏性变更**：按 `maintenance.md` §6 走"新增 `use_strict()` 过渡"，
  不动 `use()` 的冻结语义（ADR 16）。
- **清单低估了行数铁律**：迭代 1 就把余量吃掉大半（§5.1）。

### 2.3 两个提交是"事后拆出来"的

工作区里 v1.1.2 与 v1.2.0 的改动混在同一批文件里，中间状态从未提交过。做法：

1. 把最终工作区整棵树写成 git 对象（`refs/tmp/v120-snapshot`），全程可回退；
2. **反向重建** v1.1.2 状态（逐条撤销 v1.2 的改动）；
3. 提交 `b3c65df`；
4. 从快照**整树恢复**，提交 `a90e190`。

校验手段：`HEAD^{tree}` 与快照树哈希**完全相同**，且两个提交的新增行里
互不包含对方的标记词（用 1.1.2-only / 1.2-only 关键词扫描确认）。中间状态
还对上了行数：v1.1.2 恰好 **961 行 / 136 测试**，与当时的文档记录逐字吻合。

### 2.4 下游迁移：AnimaPet 内嵌内核 v1.1.1 → v1.3.0

`E:\Zcode-work\AnimaPet\anima\core` 是内核的**内嵌副本**（改前逐字节等于
上游 v1.1.1，无本地补丁）。

- **唯一破坏点**：`anima/plugins/feature_host.py` 的 `FeatureAdapter(Plugin)`
  把 `ctx` 写成**只读 property**，而 v1.2 起内核会注入 `plugin.ctx = ctx`
  → `AttributeError: property 'ctx' has no setter` → **所有 feature 模组
  装载失败**。已给 `ctx` 补 setter。
- 其余全部安全：无 `dependencies` 就地修改、不碰内核私有字段、32 处
  `provide/use` 与 2 处 `subscribe` 都走 keyword-only 兼容路径。
- 同步了 `tests/test_core/test_plugin.py` 两处旧断言（`dependencies == []`
  → `== ()`）。
- 验证：`pytest tests/` **268 passed**，含 offscreen Qt 全链路集成测试
  （真实 52 个模组走 `FeatureAdapter`）。
- **测试同步**：该仓库的 `tests/test_core/` 原本是 v1.1.1 的**裁剪副本**
  （缺 v1.1.1 的批量原子性/顺序契约测试，也没有 v1.1.2~v1.3.0 的新测试）。
  已从上游同步 13 个文件（排除 `test_examples.py`：它依赖上游的 `examples/`），
  该仓库测试数 **268 -> 345 passed**。
- 回滚副本放在**仓库外**：`E:\Zcode-work\Anima-core-old\core-animapet-v1.1.1`。
  不要用老文档里的 `anima/core.bak`——会被 `git add -A` 误提交。
- 详见 `E:\Zcode-work\AnimaPet\内核更换说明.md` 的"v1.3.0 更换记录"。

---

## 三、当前状态（复核用）

| 项 | 值 |
|---|---|
| 版本 | `anima.core.__version__ = "1.3.1"` |
| 规模 | **1197 物理行 / 622 代码行**（上限 1200 / 650；物理行余量 3 行） |
| 测试 | **200 个**，覆盖率 **99%**（最低模块 lifecycle 98%） |
| 铁律 | `check_kernel_rules.py` 通过：纯标准库 + 两个规模口径 |
| 模块 | `anima/core/` 10 个（新增 `log.py`）；另有非内核 `anima/plugins/discovery.py` |
| 示例 | `examples/` 5 个，`test_examples.py` 用子进程实跑（防示例腐烂） |
| git | `1594ae8`（文档）+ 本次 v1.3.1，均在 `master` |
| 下游 | AnimaPet 内嵌内核 = v1.3.0，`tests/test_core/` 已同步，**345 测试全绿**（该仓库另有在途未提交改动，**不是本次产物**） |

---

## 四、关键决策记录（本次新增 ADR，完整见 `docs/architecture.md` §9）

- **ADR 12** handler 异常隔离 ≠ 静默：新增 `on_error` 上报，默认写 `anima.bus`
  logger；**上报路径自身也受隔离保护**。
- **ADR 13** `disable()` 语义按**实现**定稿：它不回滚副作用，回滚只在 `unload()`。
- **ADR 14** 循环依赖报"环"而非"剩余节点"：三色 DFS 回溯真实环路。
- **ADR 15** 给 `EventBus` 加锁，**推翻** v1.1 的"不加锁"结论——关键是
  "锁内拷贝、锁外执行"，保住 handler 在调用方线程运行、慢 handler 不阻塞别人。
- **ADR 16** 用新增 `use_strict()` 而不是收紧 `use()`（`maintenance.md` §6 首个用例）。
- **ADR 17** 热插拔的失败半径与卸载守卫：`load_one` 只回滚自己；
  `unload_plugin` 有依赖方时**拒绝**而非级联。
- **ADR 18** 优先级做成"零成本默认"：只有真用过非零 priority 才排序。
- **ADR 19** 生命周期事件放在**副作用回滚之后**发（卸载者收不到自己的讣告）。
- **ADR 20** 自动发现不进内核（不属于"怎么活/怎么死/怎么通信"，且内核有行数铁律）。

---

## 五、约束与已知坑

### 5.1 规模预算（唯一悬而未决的事）

- 铁律 8 现在是**两个口径**：`raw < 1200` 物理行 + `code < 650` 代码行
  （去掉空行/注释/docstring）。原单条 `raw < 1000` 在 docstring 占比约五成后
  失真——v1.1.2 结束时 961 物理行其实只有约 500 行代码。
- 当前 **1197 / 622**：**物理行余量只剩 3 行**，代码行余 28 行。
- v1.3.0 与 v1.3.1 都**没有上调上限**，而是把新增 docstring 写紧换来的空间。
- **下次往内核加东西之前必须先决策**：精简 docstring / 把非内核关注点外移到
  `anima/plugins/`、`anima/utils/` / 或正式上调上限。

### 5.2 踩过的雷（都值得记住）

1. **`ctx` 是保留属性名**。内核 v1.2 起写 `plugin.ctx`，插件子类若声明只读
   `ctx`（property）会直接 `AttributeError`。AnimaPet 就撞上了——v1.3.1 已把它
  写进 `Plugin` 契约，并把报错换成带说明的 `LifecycleError`。
2. **git 会把相邻改动合并进同一个 hunk**。拆分提交时按 hunk 回退会连带丢掉
   另一版的内容（`bus.py` 里 `dependencies` 的改动与 `if TYPE_CHECKING: ctx`
   挨在一起）。→ 改用"按已验证锚点做行区间删除/替换"，每步断言锚点唯一。
3. **`autocrlf=true`**：比较文件哈希前必须归一化行尾，否则全都不一样——本次
   第一次比对就因此得出过"内核被本地改过"的错误结论。
4. **`test_examples.py` 的子进程编码**：`subprocess.run(text=True)` 会按本地
   编码（GBK）解码子进程输出，只影响打印中文的示例 → 表现为"单跑能过、
   全量跑偶发失败"。已显式钉 UTF-8。
5. **PowerShell 引号/here-string 极易出错**（`Test-Path 'x' + $f` 直接报参数
   错误、`Out-String` 会注入 CR 造成假阳性）。→ 改用 **git bash** 或 Python
   脚本。本机 git bash：`D:\git\Git\bin\bash.exe`（git 装在 `D:\git\Git`）。
   用法：把命令写成 `.sh` 文件再 `bash x.sh`，完全绕开 PS 的引号问题。

---

## 六、仓库与文件地图

```
Anima-v1.1/
├── HANDOVER.md            ← 本文件
├── README.md              ← 项目门面（v1.3.0）
├── anima/
│   ├── core/              ← 10 个模块，1196 行（纯标准库，v1.x 接口冻结）
│   ├── plugins/           ← 非内核：discovery（entry points 自动发现）
│   └── py.typed           ← PEP 561 标记
├── examples/              ← hello / dependency / rollback / hot_reload / priorities
├── tests/
│   ├── test_core/         ← 内核测试（含 test_rollback / test_examples）
│   └── test_plugins/      ← 自动发现测试
├── docs/                  ← CHANGELOG / architecture / core_api / maintenance
├── check_kernel_rules.py  ← raw<1200 + code<650 + 无第三方 import
└── pyproject.toml
```

| 外部路径 | 角色 |
|---|---|
| `E:\Zcode-work\work` | 内核 v1.0 上游，**冻结只读** |
| `E:\Zcode-work\AnimaPet` | 桌面宠物（内嵌内核已升到 v1.3.0） |
| `E:\Zcode-work\Anima-core-old\core-animapet-v1.1.1` | AnimaPet 旧内核回滚副本 |
| `E:\dsh-work\YingPet-v4` | 迁移源代码，只读参考 |

---

## 七、环境与复跑

```bash
BASH="/d/git/Git/bin/bash.exe"        # 本机 git 在 D:\git\Git
cd /e/Zcode-work/Anima-v1.1

./.venv/Scripts/python.exe -m pytest tests/ -q                        # 199 个
./.venv/Scripts/python.exe -m pytest tests/ --cov=anima.core --cov-report=term
./.venv/Scripts/python.exe check_kernel_rules.py                      # 铁律
./.venv/Scripts/python.exe examples/priorities.py                     # 跑示例
```

AnimaPet 侧：

```bash
cd /e/Zcode-work/AnimaPet
./.venv/Scripts/python.exe -m pytest tests/ -q                        # 268 个
```

---

## 八、参考文档

- 变更记录（逐版本）：`docs/CHANGELOG.md`
- 架构与 ADR：`docs/architecture.md`
- 接口签名：`docs/core_api.md`
- 维护指南与铁律：`docs/maintenance.md`
- 下游宠物：`E:\Zcode-work\AnimaPet\PLAN.md`、`内核更换说明.md`
