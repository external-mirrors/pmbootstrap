# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.core.chroot import ChrootType
from pmb.core.pkgrepo import pkgrepo_default_path
from pmb.helpers import logging
import os
from pathlib import Path
import pmb.chroot.binfmt
import pmb.config
import pmb.helpers.run
import pmb.install.losetup
import pmb.helpers.mount
from pmb.core import Chroot
from pmb.core.context import get_context
from pmb.init import sandbox


def mount_chroot_image(chroot: Chroot) -> None:
    """Mount an IMAGE type chroot, to modify an existing rootfs image. This
    doesn't support split images yet!"""
    # Make sure everything is nicely unmounted just to be super safe
    # this is definitely overkill
    pmb.chroot.shutdown()
    pmb.install.losetup.detach_all()

    chroot_native = Chroot.native()
    pmb.chroot.init(chroot_native)

    loopdev = pmb.install.losetup.mount(
        Path("/") / Path(chroot.name).relative_to(chroot_native.path)
    )
    pmb.helpers.mount.bind_file(loopdev, chroot_native / "dev/install")
    # Set up device mapper bits
    pmb.helpers.run.root(["kpartx", "-u", loopdev])
    chroot.path.mkdir(exist_ok=True)
    loopdev_basename = os.path.basename(loopdev)
    # # The name of the IMAGE chroot is the path to the rootfs image
    if Path(f"/dev/mapper/{loopdev_basename}p2").exists():
        pmb.helpers.run.root(["mount", f"/dev/mapper/{loopdev_basename}p2", chroot.path])
        pmb.helpers.run.root(["mount", f"/dev/mapper/{loopdev_basename}p1", chroot.path / "boot"])
    else:
        pmb.helpers.run.root(["mount", f"/dev/{loopdev_basename}", chroot.path])

    pmb.config.workdir.chroot_save_init(chroot)

    logging.info(f"({chroot}) mounted {chroot.name}")


def mount_dev_tmpfs(chroot: Chroot = Chroot.native()) -> None:
    """
    Mount tmpfs inside the chroot's dev folder to make sure we can create
    device nodes, even if the filesystem of the work folder does not support
    it.
    """
    # Do nothing when it is already mounted
    dev = chroot / "dev"
    if pmb.helpers.mount.ismount(dev):
        return

    # Use sandbox to set up /dev inside the chroot
    ttyname = os.ttyname(2) if os.isatty(2) else ""
    devop = sandbox.DevOperation(ttyname, "/dev")
    devop.execute("/", str(chroot.path))


def mount(chroot: Chroot) -> None:
    if chroot.type == ChrootType.IMAGE and not pmb.mount.ismount(chroot.path):
        mount_chroot_image(chroot)

    if not chroot.path.exists():
        os.mkdir(str(chroot.path))
    # Mount tmpfs as the chroot's /dev
    mount_dev_tmpfs(chroot)

    # Get all mountpoints
    arch = chroot.arch
    channel = pmb.config.pmaports.read_config(pkgrepo_default_path())["channel"]
    mountpoints: dict[Path, Path] = {}
    for src_template, target_template in pmb.config.chroot_mount_bind.items():
        src_template = src_template.replace("$WORK", os.fspath(get_context().config.work))
        src_template = src_template.replace("$ARCH", str(arch))
        src_template = src_template.replace("$CHANNEL", channel)
        mountpoints[Path(src_template)] = Path(target_template)

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


def remove_mnt_pmbootstrap(chroot: Chroot) -> None:
    """Safely remove /mnt/pmbootstrap directories from the chroot, without
    running rm -r as root and potentially removing data inside the
    mountpoint in case it was still mounted (bug in pmbootstrap, or user
    ran pmbootstrap 2x in parallel). This is similar to running 'rm -r -d',
    but we don't assume that the host's rm has the -d flag (busybox does
    not)."""
    mnt_dir = chroot / "mnt/pmbootstrap"

    if not mnt_dir.exists():
        return

    for path in [*mnt_dir.glob("*"), mnt_dir]:
        pmb.helpers.run.root(["rmdir", path])
