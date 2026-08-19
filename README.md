# Anima

Anima 是一个零外部依赖的 Python 插件内核：插件生命周期管理、事件总线、
服务注册表与副作用自动回滚，全部基于标准库实现。

- **内核规模**: `anima/core/` 共 735 行，仅依赖标准库
- **测试**: 104 个单元/集成/性能/压力测试，行覆盖率 99%（各模块 ≥97%）
- **Python**: >= 3.11

## 快速开始

```bash
# 使用现有虚拟环境
.venv/Scripts/python -m pytest tests/test_core/ -v     # 运行全部测试
```

## 内核使用示例

```python
import asyncio
from anima.core import App, Plugin, Context


class Database(Plugin):
    """提供 db 服务的插件。"""

    name = "database"
    version = "1.0.0"

    async def load(self, ctx: Context) -> None:
        # load 阶段：只注册自己，不使用别人的服务
        ctx.provide("db", {"connected": True})
        ctx.on("db.query", lambda d: print("query:", d))


class Weather(Plugin):
    """依赖 database 的插件。"""

    name = "weather"
    dependencies = ["database"]

    async def load(self, ctx: Context) -> None:
        self._ctx = ctx

    async def enable(self) -> None:
        # enable 阶段：依赖已全部就绪，可以安全 use()
        db = self._ctx.use("db")
        assert db is not None
        self._ctx.emit("db.query", "SELECT weather")


async def main() -> None:
    app = App()
    await app.start([Weather(), Database()])   # 乱序传入，内核自动拓扑排序
    # ... 所有插件 enabled，可自由通信
    await app.stop()                            # 副作用自动回滚，总线/注册表清空


asyncio.run(main())
```

## 核心概念

| 概念 | 模块 | 职责 |
|---|---|---|
| `App` | `anima/core/app.py` | 组装器，唯一对外入口 |
| `Plugin` | `anima/core/plugin.py` | 插件抽象基类（load/enable/disable/unload） |
| `EventBus` | `anima/core/bus.py` | 发布订阅，支持 `*` 与 `前缀.*` 通配符 |
| `ServiceRegistry` | `anima/core/registry.py` | 按名注册/发现服务 |
| `Context` | `anima/core/context.py` | 插件视角的链式 API |
| `EffectTracker` | `anima/core/effects.py` | LIFO 副作用栈，卸载时自动回滚 |
| `LifecycleManager` | `anima/core/lifecycle.py` | Kahn 拓扑排序 + 状态机 |

### 生命周期状态机

```
unloaded ──load──> loaded ──enable──> enabled
   ^                  ^                   │
   │                  └────disable────────┤
   └─────────unload（enabled 下先自动 disable）┘
```

- `load()`: 只注册自己；`enable()`: 可安全使用依赖
- 卸载按**逆拓扑顺序**执行，全部副作用（事件订阅、服务注册、自定义清理）自动回滚
- 循环/缺失依赖在加载前即抛 `DependencyError`

### 插件配置

`App.config["plugins"][插件名]` 是每个插件的私有配置切片，通过 `ctx.config` 访问，天然隔离。

## 目录结构

```
anima/
├── __init__.py
└── core/               # 内核（纯标准库，735 行）
    ├── __init__.py     # 公共 API 导出
    ├── app.py          # App 组装器
    ├── bus.py          # EventBus 事件总线
    ├── registry.py     # ServiceRegistry 服务注册表
    ├── lifecycle.py    # LifecycleManager 生命周期
    ├── context.py      # Context 插件上下文
    ├── effects.py      # EffectTracker 副作用追踪
    ├── plugin.py       # Plugin 抽象基类
    └── exceptions.py   # 异常体系
tests/
└── test_core/          # 104 个测试（覆盖率 99%）
docs/
├── core_api.md         # 接口签名
├── architecture.md     # 架构设计（分层、数据流、决策记录）
└── maintenance.md      # 开发维护指南
```

## 开发

```bash
.venv/Scripts/python -m pytest tests/test_core/ --cov=anima.core --cov-report=term
.venv/Scripts/python check_kernel_rules.py   # 行数 <1000 + 无第三方 import
```

## 内核铁律

1. `core/` 的 import 只允许标准库
2. 内核不知道角色、聊天、天气、LLM 是什么
3. 内核只回答：插件怎么活、怎么死、怎么通信
4. 所有公共接口类型注解完整
5. 所有模块行覆盖率 >= 90%
