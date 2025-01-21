# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from pathlib import Path
from pmb import commands, logging
import pmb.helpers.repo
import pmb.parse.apkindex
from pmb.core.arch import Arch
from pmb.parse import apkbuild
import time


"""Various internal test commands for performance testing and debugging."""


def apkindex_parse_all() -> None:
    indexes = pmb.helpers.repo.apkindex_files(Arch.native())

    pkgs = 0
    indxs = len(indexes)
    start = time.time()
    for index in indexes:
        ret = pmb.parse.apkindex.parse(index)
        pkgs += len(ret)
    end = time.time()
    logging.info(f"Parsed {pkgs} packages from {indxs} APKINDEX files in {end - start:.3f} seconds")


class Test(commands.Command):
    def __init__(self, action: str, file: Path|None) -> None:
        self.action = action
        self.file = file

    def run(self) -> None:
        if self.action == "apkindex_parse_all":
            apkindex_parse_all()
        elif self.action == "apkbuild_parse":
            apk = apkbuild(self.file)
            print(apk.toJSON(pretty=True))
