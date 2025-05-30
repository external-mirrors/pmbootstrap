#!/usr/bin/env python3
# -*- encoding: UTF-8 -*-
# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# PYTHON_ARGCOMPLETE_OK
import sys
import pmb
import os
from pmb.init import sandbox

# Sanitise environment a bit
os.environ["SHELL"] = "/bin/sh" if os.path.exists("/bin/sh") else "/bin/bash"

if os.geteuid() == 0:
    raise RuntimeError("pmbootstrap can't be run as root, please run it as a regular user.")

# FIXME: parse args before unshare(), this is really hacky
if "install" in sys.argv and "--disk" in sys.argv:
    from pmb.init.run import run_root
    disk = sys.argv[sys.argv.index("--disk")+1]
    if not os.access(disk, os.W_OK):
        cmd = ["sudo", "chown", str(os.getlogin()), disk]
        if "-y" in sys.argv:
            print(f"Using sudo to chown the target disk {disk}")
            print(f"  $ {' '.join(cmd)}")
            run_root(cmd)
        else:
            print(f"The target disk '{disk}' is not writable by your user. Please run the following"
                " command manually or press 'y' and enter your sudo password when prompted.")
            print(f"  $ {' '.join(cmd)}")
            ans = input("> ")
            if ans.lower() == "y":
                run_root(cmd)

sandbox.acquire_privileges(become_root=False)
# Unshare mount and PID namespaces. We create a new PID namespace so
# that any log-running daemons (e.g. adbd, sccache) will be killed when
# pmbootstrap exits
sandbox.unshare(sandbox.CLONE_NEWNS | sandbox.CLONE_NEWPID)

# We are now PID 1 in a new PID namespace. We don't want to run all our
# logic as PID 1 since subprocess.Popen() seemingly causes our PID to
# change. So we fork now, the child process continues and we just wait
# around and propagate the exit code.
# This is all kinda hacky, we should integrate this with the acquire_privileges()
# implementation since it's already doing similar fork shenanigans, we could
# save a call to fork() this way. But for now it's fine.
pid = os.fork()
if pid > 0:
    # We are PID 1! let's hang out
    pid, wstatus = os.waitpid(pid, 0)
    exitcode = os.waitstatus_to_exitcode(wstatus)
    os._exit(exitcode)

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
    ),
    # Mount binfmt_misc at /tmp/pmb_binfmt_misc
    sandbox.BinfmtOperation(pmb.config.binfmt_misc),
    # /tmp/pmb is a tmpfs we can use for scratch data that will be removed
    # on exit.
    sandbox.TmpfsOperation("/tmp/pmb"),
]
sandbox.setup_mounts(fsops)

# Reset our CWD now that we're inside the mount namespace
os.chdir(os.environ["PWD"])

# A convenience wrapper for running pmbootstrap from the git repository. This
# script is not part of the python packaging, so don't add more logic here!
if __name__ == "__main__":
    sys.exit(pmb.main())
