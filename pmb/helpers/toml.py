# Copyright 2024 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.helpers.exceptions import NonBugError
from pmb.meta import Cache

try:
    # Python >= 3.11
    from tomllib import TOMLDecodeError, load  # novermin
except ImportError:
    # Python < 3.11
    from tomli import TOMLDecodeError, load  # type:ignore[import-not-found,no-redef,assignment]


@Cache("path")
def load_toml_file(path) -> dict:
    """Read a toml file into a dict and show the path on error."""
    with open(path, mode="rb") as f:
        try:
            return load(f)
        except TOMLDecodeError as e:
            raise NonBugError(f"{path}: {e}")
