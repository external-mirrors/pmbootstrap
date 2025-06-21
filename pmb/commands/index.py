# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from pmb import commands
import pmb.build.other
import pmb.chroot
from pmb.core.chroot import Chroot


class Index(commands.Command):
    def __init__(self) -> None:
        pass

    def run(self) -> None:
        # Set up native chroot for running commands
        pmb.chroot.init(Chroot.native())
        pmb.build.other.index_repo()
