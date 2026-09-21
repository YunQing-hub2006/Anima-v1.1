"""P4-4 - 示例可运行性测试：examples/ 下的脚本不能腐烂。

用**子进程**按 README 写的方式跑（python examples/xxx.py），而不是在 pytest
进程里 import —— 后者会因为 pytest 的 pythonpath=. 掩盖掉"示例自己跑不起来"
的问题（v1.2 实现时就踩过这个坑：在 pytest 里全绿，命令行直接报
ModuleNotFoundError）。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


@pytest.mark.parametrize("name", ["hello", "dependency", "rollback", "hot_reload"])
def test_example_runs_as_script(name: str):
    """每个示例都能按 README 的命令直接跑通，且有输出。"""
    path = EXAMPLES / f"{name}.py"
    assert path.is_file(), f"缺少示例: {path}"

    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"{name} 退出码 {proc.returncode}\n{proc.stderr}"
    assert proc.stdout.strip(), f"{name} 没有任何输出"
