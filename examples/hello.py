"""最小可运行示例：一个插件 + 一次事件往返。

运行：python examples/hello.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# 让示例既能按 `python examples/xxx.py` 直接跑，也能被测试进程 import。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from anima.core import App, Context, Plugin


class Greeter(Plugin):
    name = "greeter"

    async def load(self, ctx: Context) -> None:
        ctx.on("hello", lambda who: print("  收到 hello:", who))

    async def enable(self) -> None:
        # v1.2 起框架已注入 self.ctx，不必自己保存 load 的参数
        self.ctx.emit("hello", "world")


async def main() -> None:
    app = App()
    await app.start([Greeter()])
    await app.stop()
    print("  停止后 bus 订阅数:", app.bus.count())
    print("  停止后 registry:", app.registry.list())


if __name__ == "__main__":
    asyncio.run(main())
