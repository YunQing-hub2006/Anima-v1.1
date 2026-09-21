"""热插拔示例（v1.2）：运行中装卸单个插件。

运行：python examples/hot_reload.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# 让示例既能按 `python examples/xxx.py` 直接跑，也能被测试进程 import。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from anima.core import App, Context, Plugin


class Resident(Plugin):
    name = "resident"

    async def load(self, ctx: Context) -> None:
        print("  load: resident")


class Late(Plugin):
    name = "late"
    dependencies = ["resident"]  # 依赖已经跑着的插件

    async def load(self, ctx: Context) -> None:
        print("  load: late")
        ctx.provide("late-svc", "hot")


async def main() -> None:
    app = App()
    await app.start([Resident()])

    await app.load_plugin(Late())
    print("  late 状态:", app.lifecycle.get_state("late"))
    print("  late-svc:", app.registry.use("late-svc"))

    await app.unload_plugin("late")
    print("  卸载后 late-svc:", app.registry.use("late-svc"))
    print("  resident 仍在运行:", app.lifecycle.get_state("resident"))

    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
