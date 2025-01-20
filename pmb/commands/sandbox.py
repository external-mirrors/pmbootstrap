# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from pmb.core.chroot import Chroot
from pmb import commands
from pmb.core.sandbox import ChrootSandbox, HostSandbox
import os


class Sandbox(commands.Command):
    def __init__(self, chroot: bool, persistent: bool):
        self.chroot = chroot
        self.persistent = persistent

    def run(self):
        # run_sandboxed(["busybox", "sh", "-i"])
        if self.chroot:
            sandbox = ChrootSandbox(Chroot.native(), persistent=self.persistent)
        else:
            sandbox = HostSandbox()

        sandbox.with_chdir(os.getcwd()).build().run(["sh", "-i"], interactive=True)
