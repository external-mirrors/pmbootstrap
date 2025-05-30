# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path
import time

from pmb.types import PmbArgs
import pmb.helpers.run
import pmb.helpers.pmaports


def replace(path: Path, old: str, new: str) -> None:
    text = ""
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read()

    text = text.replace(old, new)

    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)


def replace_apkbuild(
    args: PmbArgs, pkgname: str, key: str, new: int | str, in_quotes: bool = False
) -> None:
    """Replace one key=value line in an APKBUILD and verify it afterwards.

    :param pkgname: package name, e.g. "hello-world"
    :param key: key that should be replaced, e.g. "pkgver"
    :param new: new value
    :param in_quotes: expect the value to be in quotation marks ("")
    """
    # Read old value
    path = pmb.helpers.pmaports.find(pkgname) / "APKBUILD"
    apkbuild = pmb.parse.apkbuild(path)
    old = apkbuild[key]

    # Prepare old/new strings
    if in_quotes:
        line_old = f'{key}="{old}"'
        line_new = f'{key}="{new}"'
    else:
        line_old = f"{key}={old}"
        line_new = f"{key}={new}"

    # Replace
    replace(path, "\n" + line_old + "\n", "\n" + line_new + "\n")

    # Verify
    pmb.parse.apkbuild.cache_clear()
    apkbuild = pmb.parse.apkbuild(path)
    if apkbuild[key] != str(new):
        raise RuntimeError(
            f"Failed to set '{key}' for pmaport '{pkgname}'. Make sure"
            f" that there's a line with exactly the string '{line_old}'"
            f" and nothing else in: {path}"
        )

def is_older_than(path: Path, seconds: int) -> bool:
    """Check if a single file is older than a given amount of seconds."""
    if not os.path.exists(path):
        return True
    lastmod = os.path.getmtime(path)
    return lastmod + seconds < time.time()
