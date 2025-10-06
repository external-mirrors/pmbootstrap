# Copyright 2025 Casey Connolly
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Set up the base sysroot for operating in, pmb pivots into
# this rootfs and treats it as the "host" environment.

from pathlib import Path
import os

from pmb.helpers import apk_static
from pmb.helpers.apk import update_repository_list, run as run_apk
import pmb.config
from pmb.config.workdir import chroot_save_init, chroots_outdated
import pmb.chroot
from pmb.core.chroot import Sysroot
from . import sandbox
from pmb.core.arch import Arch

def create_stub_passwd(rootfs: Path) -> str:
    """
    Create a version of /etc/passwd where the current user is root and we use sh
    as the shell.
    """
    # Get the existing passwd and remove the root entry
    with open(rootfs / "etc/passwd") as passwd:
        contents = list(filter(lambda line: not line.startswith("root:x:0:0"), passwd.readlines()))
        return f"{os.getlogin()}:x:0:0:{os.getlogin()}:{os.environ['HOME']}:/bin/sh\n" + \
            "\n".join(contents)

class PmbSandboxBuilder:
    """
    Configure the sandboxed environment that pmb will pivot into
    """
    fsops: list[sandbox.FSOperation]
    sysroot: Path
    work: Path

    def __init__(self, *,
                 work: Path,
                 cache: Path,
                 aports: list[Path],
                 sysroot: Path):
        self.sysroot = sysroot
        self.work = work
        
        sysroot.mkdir(exist_ok=True)

        # Make sure we have a cache dir
        (cache / f"apk_{Arch.native()}").mkdir(exist_ok=True)

        # Set setting up our mounts
        self.fsops = [
            # FIXME: why does this simply NOT WORK??!?!?!?
            sandbox.BindOperation(
                f"{self.sysroot}/usr",
                "/usr",
                readonly=False,
                required=True,
                relative=False,
            ),
            sandbox.TmpfsOperation(
                "/tmp",
            ),
            # Bind resolv.conf from the host
            sandbox.BindOperation(
                "/etc/resolv.conf",
                "/etc/resolv.conf",
                readonly=True,
                required=True,
                relative=False
            ),
            # Make the users .ssh directory available so ssh will work
            # but keep it readonly
            sandbox.BindOperation(
                os.environ['HOME'] + "/.ssh",
                os.environ['HOME'] + "/.ssh",
                readonly=True,
                required=False,
                relative=False
            ),
            # Mount binfmt_misc at /tmp/pmb_binfmt_misc
            sandbox.BinfmtOperation(pmb.config.binfmt_misc),
            # Mount cache and work dirs
            sandbox.BindOperation(
                str(cache),
                "/cache",
                readonly=False,
                required=True,
                relative=False
            ),
            sandbox.BindOperation(
                str(work),
                "/work",
                readonly=False,
                required=True,
                relative=False
            ),
            # Mount the current working directory
            sandbox.BindOperation(
                os.curdir,
                os.curdir,
                readonly=False,
                required=True,
                relative=False
            ),
            # Mount the apk cache from the newroot cache dir
            sandbox.BindOperation(
                (cache / f"apk_{Arch.native()}"),
                "/var/cache/apk",
                readonly=False,
                required=True,
                relative=False
            ),
            # *[
            #     sandbox.BindOperation(
            #         str(pkgdir),
            #         str(pkgdir),
            #         readonly=False,
            #         required=True,
            #         relative=False
            #     ) for pkgdir in aports
            # ],
        ]


    # Enter sandbox!
    def enter(self):
        # Set up and init the sysroot
        self._setup_sysroot()
        
        # Set up and enter the sandbox
        self._setup_sandbox()


    def _setup_sandbox(self):

        # Now that we know passwd exists
        self.fsops.extend((
            # Map out own /etc/passwd for our user to become root
            sandbox.WriteOperation(
                create_stub_passwd(self.sysroot),
                "/tmp/passwd",
            ),
            sandbox.BindOperation(
                "/tmp/passwd",
                "/etc/passwd",
                readonly=True,
                required=True,
                relative=True,
            ),
        ))
        
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

        # Now pivot into the sysroot!
        sandbox.setup_mounts(self.fsops)
        print("Setup mount!")

        # Reset our CWD now that we're inside the mount namespace
        os.chdir(os.environ["PWD"])


    def _setup_sysroot(self):
        """
        Setup the sysroot for us to pivot into. Similar to chroot.init()
        """
        apk_static.init()
        chroot = Sysroot()

        sysroot = self.sysroot
        if (sysroot / "etc/apk/arch").exists():
            # If the sysroot already exists, update if need be
            if chroots_outdated("sysroot"):
                pmb.logging.info("sysroot is outdated! Updating...")
                run_apk(["upgrade", "-a"], sysroot)
            return

        sysroot.mkdir(exist_ok=True)
        # Set up the /usr merge
        (sysroot / "usr/bin").mkdir(parents=True, exist_ok=True)
        (sysroot / "usr/lib").mkdir(parents=True, exist_ok=True)
        (sysroot / "usr/sbin").mkdir(parents=True, exist_ok=True)
        for d in ["bin", "sbin", "lib"]:
            dp = (sysroot / d)
            dp.unlink(missing_ok=True)
            dp.symlink_to(f"usr/{d}")

        # Copy in the keys
        pmb.chroot.init_keys(sysroot)
        # Set up /etc/apk/repositories
        update_repository_list(sysroot)

        chroot_save_init("sysroot")

        # Install everything we need
        pkgs = ["alpine-baselayout", "apk-tools", "busybox", "musl-utils"]
        pkgs = [*pkgs, *list(map(lambda cmd: f"cmd:{cmd}", pmb.config.required_programs.keys()))]
        # Run in usermode since we aren't in the sandbox yet, when we pivot in our
        # user account will become UID 0
        run_apk(["--usermode", "add", "--initdb", *pkgs], chroot)
