# Copyright 2026 Rakshit Kumar Singh, Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from collections.abc import Sequence

import pmb.helpers.pmaports
from pmb.core.arch import Arch
from pmb.helpers import logging


def apkbuild_parse(packages: Sequence[str], arch: Arch | None = None) -> None:
    # Default to all packages
    if not packages:
        packages = pmb.helpers.pmaports.get_list()

    logging.info(f"Parsing packages {', '.join(packages)} for arch {arch}")
    # Iterate over all packages
    print("{")
    first = True
    for package in packages:
        if not first:
            print(",")
            first = False
        print(f'"{package}":', end="")
        aport = pmb.helpers.pmaports.get(package, arch=arch)
        print(json.dumps(aport, indent=4, sort_keys=True), end="")
    print("\n}")
