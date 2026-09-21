"""事件优先级与请求-响应示例（v1.3）：priority + emit_collect。

运行：python examples/priorities.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# 让示例既能按 `python examples/xxx.py` 直接跑，也能被测试进程 import。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from anima.core import App, Context, Plugin


class Auth(Plugin):
    name = "auth"

    async def load(self, ctx: Context) -> None:
        # 优先级大的先跑：认证链上"管理员放行"要先于"默认拒绝"表态
        ctx.on("auth.check", lambda who: "deny:anonymous", priority=-10)
        ctx.on("auth.check", lambda who: f"allow:{who}", priority=10)


class Router(Plugin):
    name = "router"
    dependencies = ["auth"]
    config_defaults = {"retries": 2}

    async def load(self, ctx: Context) -> None:
        print("  配置默认值已就位:", self.ctx.config)

    async def enable(self) -> None:
        answers = await self.ctx.emit_collect("auth.check", "alice")
        print("  收集到的应答:", answers)
        print("  首个应答（优先级最高）:", answers[0])


async def main() -> None:
    app = App()
    await app.start([Router(), Auth()])   # 乱序传入，内核自动拓扑排序
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
