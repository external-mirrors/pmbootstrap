# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.core.pkgrepo import pkgrepo_default_path
from pmb.helpers import logging
import os
from pathlib import Path
import pmb.chroot.binfmt
import pmb.config
import pmb.helpers.run
import pmb.helpers.mount
from pmb.core import Chroot
from pmb.core.context import get_context
from pmb.init import sandbox


def mount_dev_tmpfs(chroot: Chroot = Chroot.native()) -> None:
    """
    Mount tmpfs inside the chroot's dev folder to make sure we can create
    device nodes, even if the filesystem of the work folder does not support
    it.
    """
    # Do nothing when it is already mounted
    # dev = chroot / "dev"
    # if pmb.helpers.mount.ismount(dev):
    #     return

    logging.info(f"mount_dev_tmpfs({chroot})")

    # Use sandbox to set up /dev inside the chroot
    ttyname = os.ttyname(2) if os.isatty(2) else ""
    devop = sandbox.DevOperation(ttyname, "/dev")
    devop.execute("/", str(chroot.path))


def mount(chroot: Chroot):
    # Mount tmpfs as the chroot's /dev
    chroot.path.mkdir(exist_ok=True)
    mount_dev_tmpfs(chroot)

    # Get all mountpoints
    arch = chroot.arch
    config = get_context().config
    mountpoints: dict[Path, Path] = {}
    for src_template, target_template in pmb.config.chroot_mount_bind.items():
        src_template = src_template.replace("$CACHE", os.fspath(config.cache))
        src_template = src_template.replace("$ARCH", str(arch))
        src_template = src_template.replace("$PACKAGES", os.fspath(config.work / "packages"))
        mountpoints[Path(src_template).resolve()] = Path(target_template)

    # Mount if necessary
    for source, target in mountpoints.items():
        target_outer = chroot / target
        if not pmb.helpers.mount.ismount(target_outer):
            pmb.helpers.mount.bind(source, target_outer)

    # Set up binfmt
    if not arch.cpu_emulation_required():
        return

    arch_qemu = arch.qemu_user()

    # mount --bind the qemu-user binary
    pmb.chroot.binfmt.register(arch)
    pmb.helpers.mount.bind_file(
        Chroot.native() / f"usr/bin/qemu-{arch_qemu}",
        chroot / f"usr/bin/qemu-{arch_qemu}-static",
        create_folders=True,
    )


def mount_native_into_foreign(chroot: Chroot) -> None:
    source = Chroot.native().path
    target = chroot / "native"
    pmb.helpers.mount.bind(source, target)

    musl = next(source.glob("lib/ld-musl-*.so.1")).name
    musl_link = chroot / "lib" / musl
    if not musl_link.is_symlink():
        pmb.helpers.run.root(["ln", "-s", "/native/lib/" + musl, musl_link])
        # pmb.helpers.run.root(["ln", "-sf", "/native/usr/bin/pigz", "/usr/local/bin/pigz"])


def umount_all(chroot: Chroot) -> None:
    """Unmount all bind mounts inside a chroot."""
    if not chroot.is_mounted():
        import warnings
        warnings.warn(f"({chroot}) Tried to umount inactive chroot! This will become an error in the future.", DeprecationWarning)
        return

    pmb.helpers.mount.umount_all(chroot.path)
