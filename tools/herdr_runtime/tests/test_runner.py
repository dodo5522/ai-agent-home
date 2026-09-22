from pathlib import Path

import pytest

from herdr_runtime import RuntimeCommandError, SubprocessRunner


def test_missing_command_raises_runtime_command_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeCommandError, match="cannot execute"):
        SubprocessRunner().run([str(tmp_path / "missing")])
