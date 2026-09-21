"""拓扑排序示例：乱序传入，内核按依赖顺序加载。

运行：python examples/dependency.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# 让示例既能按 `python examples/xxx.py` 直接跑，也能被测试进程 import。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from anima.core import App, Context, Plugin


class Database(Plugin):
    name = "database"

    async def load(self, ctx: Context) -> None:
        print("  load: database")
        ctx.provide("db", "sqlite://memory")


class Repository(Plugin):
    name = "repository"
    dependencies = ["database"]

    async def load(self, ctx: Context) -> None:
        print("  load: repository")

    async def enable(self) -> None:
        # 依赖已就绪，use 一定拿得到
        print("  enable: repository 拿到 db =", self.ctx.use("db"))


class Api(Plugin):
    name = "api"
    dependencies = ["repository"]

    async def load(self, ctx: Context) -> None:
        print("  load: api")


async def main() -> None:
    app = App()
    print("  传入顺序: api, repository, database")
    await app.start([Api(), Repository(), Database()])  # 故意乱序
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
