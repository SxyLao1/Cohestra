from __future__ import annotations

import os
from pathlib import Path

import pytest

from cohestra.adapters.contracts import Capability, DispatchRequest
from cohestra.adapters.filesystem import _junction_command, get_link_strategy


def test_dispatch_request_requires_stable_identifiers() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        DispatchRequest("", "adapter", Capability.DISPATCH)


def test_platform_selection_rejects_unsupported_combinations() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        get_link_strategy("linux", "junction")
    if os.name != "nt":
        with pytest.raises(RuntimeError, match="Windows junction"):
            get_link_strategy("windows", "junction")
    else:
        assert callable(get_link_strategy("windows", "junction"))


def test_junction_command_quotes_paths_and_rejects_command_metacharacters(
    tmp_path: Path,
) -> None:
    command = _junction_command(tmp_path / "source folder", tmp_path / "target folder")
    assert command.startswith('mklink /J "')
    assert '" "' in command
    with pytest.raises(ValueError, match="unsupported"):
        _junction_command(tmp_path / "source&next", tmp_path / "target")
