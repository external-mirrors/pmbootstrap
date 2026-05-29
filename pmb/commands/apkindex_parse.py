# Copyright 2026 Oliver Smith, Paul Adam
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path

import pmb.parse.apkindex
from pmb.core.apkindex_block import ApkindexBlockEncoder


def apkindex_parse(apkindex_path: Path, package: str | list[str]) -> None:
    result = pmb.parse.apkindex.parse(apkindex_path)
    if package:
        if package not in result:
            raise RuntimeError(f"Package not found in the APKINDEX: {package}")
        print(json.dumps(result[package], indent=4, cls=ApkindexBlockEncoder))
    else:
        print(json.dumps(result, indent=4, cls=ApkindexBlockEncoder))
