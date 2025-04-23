#!/usr/bin/env python3
# -*- encoding: UTF-8 -*-
# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# PYTHON_ARGCOMPLETE_OK
import sys
import pmb
import os
from pmb.init import sandbox

original_uid = os.geteuid()

sandbox.acquire_privileges(become_root=False)
# Unshare mount namespace
sandbox.unshare(sandbox.CLONE_NEWNS)
# sandbox.seccomp_suppress(chown=True)

# print("Caps: ")
# with open("/proc/self/status", "rb") as f:
#     for line in f.readlines():
#         if line.startswith(b"CapEff:"):
#             print(line)

# print(f"cap_sys_admin: {sandbox.have_effective_cap(sandbox.CAP_SYS_ADMIN)}")
# print(f"single user: {sandbox.userns_has_single_user()}")

# We set up a very basic mount environment, where we just bind mount the host
# rootfs in. We can extend this in the future to isolate the pmb workdir but
# for now this is enough.
fsops = [
    sandbox.BindOperation(
        "/",
        "/",
        readonly=False,
        required=True,
        relative=False,
    )
]
sandbox.setup_mounts(fsops)

# A convenience wrapper for running pmbootstrap from the git repository. This
# script is not part of the python packaging, so don't add more logic here!
if __name__ == "__main__":
    sys.exit(pmb.main(original_uid=original_uid))
