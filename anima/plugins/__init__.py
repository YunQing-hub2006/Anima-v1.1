"""Anima 插件层（非内核）：扩展能力与业务插件住在这里。

内核只回答"插件怎么活、怎么死、怎么通信"，别的都默认放这一层，以免顶破
``anima/core/`` 的规模铁律（见 docs/maintenance.md 铁律 8）。
"""

from anima.plugins.discovery import DEFAULT_GROUP, discover_plugins

__all__ = ["DEFAULT_GROUP", "discover_plugins"]
