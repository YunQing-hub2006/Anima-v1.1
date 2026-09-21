"""插件自动发现（P4-2）：从 importlib.metadata entry points 装载插件。

第三方包只要在自己的 pyproject.toml 里声明

.. code-block:: toml

    [project.entry-points."anima.plugins"]
    my-plugin = "my_package.plugin:MyPlugin"

就会被 ``discover_plugins()`` 自动发现，使用者不必手写
``app.start([A(), B(), C()])``。

**为什么不在内核里**：这不属于"插件怎么活/怎么死/怎么通信"，而且内核有
行数铁律（maintenance.md 第 8 条）。所以它住在 ``anima/plugins/``。
"""

from __future__ import annotations

import importlib.metadata as metadata
from collections.abc import Iterable
from typing import Any

from anima.core import Plugin

__all__ = ["DEFAULT_GROUP", "discover_plugins"]

#: 默认的 entry point 组名。
DEFAULT_GROUP = "anima.plugins"


def discover_plugins(
    group: str = DEFAULT_GROUP,
    *,
    entry_points: Iterable[Any] | None = None,
) -> list[Plugin]:
    """按 entry point 组装载插件实例，按 entry point 名排序（结果确定）。

    entry point 的 value 可以是 ``Plugin`` 子类，也可以是无参工厂函数。
    返回的不是 ``Plugin`` 实例时抛 ``TypeError``——宁可启动前就炸，也不要
    带着一个坏插件跑起来。``entry_points`` 参数供测试注入，默认真查已安装
    的分发包。
    """
    found = metadata.entry_points(group=group) if entry_points is None else entry_points
    plugins: list[Plugin] = []
    for entry_point in sorted(found, key=lambda ep: ep.name):
        plugin = entry_point.load()()
        if not isinstance(plugin, Plugin):
            raise TypeError(
                f"entry point {entry_point.name!r} 未返回 Plugin 实例: {type(plugin).__name__}"
            )
        plugins.append(plugin)
    return plugins
