# Copyright 2024 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from tomllib import TOMLDecodeError, load
from typing import Any

from pmb.helpers.exceptions import NonBugError
from pmb.meta import Cache

TomlTable = dict[str, Any]


@Cache("path")
def load_toml_file(path: Path) -> TomlTable:
    """Read a toml file into a dict and show the path on error."""
    with open(path, mode="rb") as f:
        try:
            return load(f)
        except TOMLDecodeError as e:
            raise NonBugError(f"{path}: {e}") from e
