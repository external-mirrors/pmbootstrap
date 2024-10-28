# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from pmb import commands, logging
import pmb.helpers.repo
import pmb.parse.apkindex
from pmb.core.arch import Arch
import time
import pmb.helpers.run


"""Various internal test commands for performance testing and debugging."""


def apkindex_parse_all():
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
    def __init__(self, action: str, sandbox_args: list[str]):
        self.action = action
        self.sandbox_args = sandbox_args

    def run(self):
        if self.action == "apkindex_parse_all":
            apkindex_parse_all()
        elif self.action == "sandbox":
            pmb.helpers.run.sandbox(["/bin/sh", "-i"])
