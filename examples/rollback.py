"""失败回滚示例：load 抛异常，此前登记的副作用全部撤销。

运行：python examples/rollback.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# 让示例既能按 `python examples/xxx.py` 直接跑，也能被测试进程 import。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from anima.core import App, Context, Plugin


class Unstable(Plugin):
    name = "unstable"

    async def load(self, ctx: Context) -> None:
        ctx.provide("unstable-svc", "half-registered")
        ctx.on("ping", lambda d: print("  不该被调用:", d))
        print("  已登记两项副作用，然后 load 失败")
        raise RuntimeError("模拟 load 失败")


async def main() -> None:
    app = App()
    try:
        await app.start([Unstable()])
    except RuntimeError as exc:
        print("  start 失败并原样抛出:", exc)

    print("  registry:", app.registry.list())
    print("  bus 订阅数:", app.bus.count())
    print("  插件状态:", app.lifecycle.get_state("unstable"))

    # 失败后没有半加载状态残留，App 可以直接重新 start
    await app.start([])
    print("  重新 start 成功")
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
