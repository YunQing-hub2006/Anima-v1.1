# Anima（v1.3.1）

零外部依赖的 Python 插件内核。它只回答三个问题：**插件怎么活、怎么死、
怎么通信**——插件生命周期管理、事件总线、服务注册表、副作用自动回滚，
全部基于标准库实现。

| | |
|---|---|
| **规模** | `anima/core/` 1197 物理行（其中**代码 622 行**；上限 1200 / 650） |
| **测试** | 200 个，行覆盖率 **99%**（最低模块 98%） |
| **依赖** | 无（纯标准库） |
| **Python** | >= 3.11 |
| **类型** | 自带 `py.typed`（PEP 561），mypy / pyright 可直接读取内联注解 |
| **变更历史** | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

---

## 30 秒上手

```python
import asyncio
from anima.core import App, Context, Plugin


class Database(Plugin):
    """提供 db 服务的插件。"""

    name = "database"

    async def load(self, ctx: Context) -> None:
        # load 阶段：只注册自己，不要 use() 别人的服务
        ctx.provide("db", {"connected": True}, interface=dict)
        ctx.on("db.query", lambda sql: print("  query:", sql))


class Weather(Plugin):
    """依赖 database 的插件。"""

    name = "weather"
    dependencies = ["database"]              # 依赖的插件名
    config_defaults = {"city": "Shanghai"}   # 缺失的配置项自动补默认值

    async def load(self, ctx: Context) -> None:
        # load() 是唯一必须实现的方法；本插件没有要对外注册的东西，留空即可
        ...

    async def enable(self) -> None:
        # enable 阶段：依赖已就绪；框架已注入 self.ctx，不必自己保存
        db = self.ctx.use_strict("db")
        print("  db =", db, "| city =", self.ctx.config["city"])
        self.ctx.emit("db.query", "SELECT weather")


async def main() -> None:
    app = App()
    await app.start([Weather(), Database()])   # 乱序传入，内核自动拓扑排序
    await app.stop()                           # 副作用自动回滚，总线/注册表清空


if __name__ == "__main__":
    asyncio.run(main())
```

实际输出（这段代码在仓库里跑过，不是示意）：

```
  db = {'connected': True} | city = Shanghai
  query: SELECT weather
```

---

## 能做什么

| 能力 | 入口 | 说明 |
|---|---|---|
| 生命周期 | `App.start / stop`、`Plugin.load / enable / disable / unload` | 依赖拓扑排序；失败按逆序原子回滚，不留半加载状态 |
| 事件总线 | `ctx.on / emit`、`EventBus` | `*` 与 `前缀.*` 通配、`priority` 优先级、`emit_collect()` 请求-响应 |
| 服务 | `ctx.provide / use / use_strict` | 按名注册；`interface=` 做类型校验；`use_strict` 取不到就抛 |
| 配置 | `ctx.config`、`Plugin.config_defaults` | 每插件私有切片；声明式默认值，**显式配置优先** |
| 副作用回滚 | `ctx.on / provide / on_cleanup / task` | LIFO；卸载时自动撤销；单项失败不中断其余 |
| 后台任务 | `ctx.task(coro)` | 卸载时 cancel 并**等待真正结束**（finally 会执行） |
| 热插拔 | `App.load_plugin / unload_plugin` | 运行时装卸单个插件；加载失败只回滚自己，有依赖方时拒绝卸载 |
| 自动发现 | `anima.plugins.discover_plugins()`（**非内核**） | 从 importlib entry points 装载，按名排序 |
| 可观测 | `anima` logger、`EventBus(on_error=...)` | handler 异常仍然隔离，但不再无声 |

---

## 生命周期

```
unloaded ──load──> loaded ──enable──> enabled
   ^                  ^                   │
   │                  └────disable────────┤
   └─────────unload（enabled 下先自动 disable）┘
```

- `load()` 是**唯一必须实现**的方法：只注册自己（provide / 订阅），不要
  `use()` 别人的服务
- `enable()` 时依赖已就绪，可以安全 `use()`
- `disable()` 停止对外活动，但**不回滚副作用**——订阅与注册保留到 `unload()`
- `unload()` 才统一回滚，随后调用插件自己的 `unload()`
- 卸载按**逆拓扑顺序**；循环/缺失依赖在加载前就抛 `DependencyError`
  （有环时消息直接给出环路路径，如 `a -> b -> a`）

### 生命周期事件

| 事件（payload = 插件名） | 时机 |
|---|---|
| `kernel.plugin.loaded` | 每个插件 `load()` 成功后 |
| `kernel.plugin.enabled` | 每个插件 `enable()` 成功后 |
| `kernel.plugin.unloaded` | `unload()` 完成、**副作用回滚之后** |

订阅 `ctx.on("kernel.plugin.*", handler)` 即可横向协作。`unloaded` 特意放在
回滚之后，所以卸载中的插件**收不到自己的讣告**。

---

## 关键语义速查

- **异常隔离**：单个事件 handler / cleanup 抛异常不影响其他组件，也不上抛给
  发布方；handler 的异常经 `on_error` 上报（默认写 `anima.bus` logger）。
- **回滚完整性**：LIFO；单项失败继续回滚，最后聚合为 `RollbackError`
  （子异常在 `.errors`，`__cause__` 指向第一个）。
- **线程**：订阅表由 `RLock` 保护，**任意线程**可订阅/退订；但**锁不跨越
  handler 执行**——handler 始终在调用方线程运行。
- **冻结语义**：`use()` 未注册返回 `default`（v1.x 内不变）；要"取不到就报错"
  请用 `use_strict()`。
- **保留属性名**：`ctx` / `name` / `version` / `dependencies` /
  `config_defaults` 由框架读写，插件不要自己声明同名的**只读 property**
  （框架写 `plugin.ctx` 会失败；v1.3.1 起报带说明的 `LifecycleError`）。

---

## 目录结构

```
anima/
├── core/               # 内核（纯标准库，1197 行 / 代码 622 行）
│   ├── __init__.py     # 公共 API 导出
│   ├── app.py          # App 组装器（start/stop、单插件热插拔）
│   ├── bus.py          # EventBus 事件总线（通配、优先级、线程安全）
│   ├── registry.py     # ServiceRegistry 服务注册表
│   ├── lifecycle.py    # LifecycleManager 拓扑排序 + 状态机 + 生命周期事件
│   ├── context.py      # Context 插件上下文（唯一窗口）
│   ├── effects.py      # EffectTracker LIFO 副作用栈
│   ├── plugin.py       # Plugin 抽象基类
│   ├── exceptions.py   # 异常体系
│   └── log.py          # 日志出口（anima logger）
├── plugins/            # 插件层（非内核）：discovery entry-point 自动发现
└── py.typed            # PEP 561 标记
examples/               # hello / dependency / rollback / hot_reload / priorities
tests/
├── test_core/          # 内核测试（含 test_rollback、test_examples）
└── test_plugins/       # 自动发现测试
docs/
├── CHANGELOG.md        # 变更记录
├── architecture.md     # 架构设计、ADR、并发模型
├── core_api.md         # 接口签名
└── maintenance.md      # 开发维护指南
```

---

## 开发

```bash
.venv/Scripts/python -m pytest tests/ -q                              # 200 个测试
.venv/Scripts/python -m pytest tests/ --cov=anima.core --cov-report=term
.venv/Scripts/python check_kernel_rules.py    # raw<1200 + code<650 + 无第三方 import
.venv/Scripts/python examples/hello.py        # 跑一个最小示例
```

---

## 内核铁律

1. `core/` 的 import 只允许标准库（`check_kernel_rules.py` 自动校验）
2. 内核不知道角色、聊天、天气、LLM 是什么
3. 内核只回答：插件怎么活、怎么死、怎么通信
4. 所有公共接口类型注解完整
5. 每个模块行覆盖率 >= 90%
6. `core/` 规模双口径：`raw < 1200` 物理行且 `code < 650` 代码行

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 分层、数据流、ADR 决策记录、并发模型、演进方向 |
| [docs/core_api.md](docs/core_api.md) | 全部公共接口签名与逐版本变更记录 |
| [docs/maintenance.md](docs/maintenance.md) | 铁律、变更流程、逐模块不变式、常见问题诊断 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 逐版本变更与验收数据 |
| [HANDOVER.md](HANDOVER.md) | 开发会话交接记录（含踩坑清单） |
