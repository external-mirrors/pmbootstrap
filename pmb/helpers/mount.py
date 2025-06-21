# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path, PurePath
import pmb.helpers
from pmb.core import Chroot
from pmb.types import PathString
from pmb.init import sandbox


def ismount(folder: Path) -> bool:
    """Ismount() implementation that works for mount --bind.

    Workaround for: https://bugs.python.org/issue29707
    """
    folder = folder.resolve()
    with open("/proc/mounts") as handle:
        for line in handle:
            words = line.split()
            if len(words) >= 2 and Path(words[1]) == folder:
                return True
            if words[0] == folder:
                return True
    return False


def bind(
    source: PathString, destination: Path, create_folders: bool = True, umount: bool = False
) -> None:
    """Mount --bind a folder and create necessary directory structure.

    :param umount: when destination is already a mount point, umount it first.
    """
    # Check/umount destination
    if ismount(destination):
        if umount:
            umount_all(destination)
        else:
            return

    # Check/create folders
    if create_folders:
        for path in [source, destination]:
            Path(path).mkdir(exist_ok=True, parents=True)

    pmb.logging.verbose(f"mount --bind {source} {destination}")
    # Actually mount the folder
    sandbox.mount_rbind(str(source), str(destination))

    # Verify that it has worked
    if not ismount(destination):
        raise RuntimeError(f"Mount failed: {source} -> {destination}")


def bind_file(source: Path, destination: Path, create_folders: bool = False) -> None:
    """Mount a file with the --bind option, and create the destination file, if necessary."""
    # Skip existing mountpoint
    if ismount(destination):
        return

    # Create empty file
    if not destination.exists():
        if create_folders:
            dest_dir: Path = destination.parent
            if not dest_dir.is_dir():
                os.makedirs(dest_dir, exist_ok=True)

        with sandbox.umask(~0o644):
            os.close(os.open(destination, os.O_CREAT | os.O_CLOEXEC | os.O_EXCL))

    # Mount
    pmb.logging.info(f"% mount --bind {source} {destination}")
    sandbox.mount_rbind(str(source), str(destination), 0)


def umount_all_list(prefix: Path, source: Path = Path("/proc/mounts")) -> list[Path]:
    """Parse `/proc/mounts` for all folders beginning with a prefix.

    :source: can be changed for testcases

    :returns: a list of folders that need to be umounted

    """
    ret = []
    prefix = prefix.resolve()
    with source.open() as handle:
        for line in handle:
            words = line.split()
            if len(words) < 2:
                raise RuntimeError(f"Failed to parse line in {source}: {line}")
            mountpoint = Path(words[1].replace(r"\040(deleted)", ""))
            if mountpoint.is_relative_to(prefix):  # is subpath
                ret.append(mountpoint)
    ret.sort(reverse=True)
    return ret


def umount_all(folder: Path) -> None:
    """Umount all folders that are mounted inside a given folder."""
    all_mountpoints = umount_all_list(folder)
    if all_mountpoints:
        pmb.logging.info(f"% umount -R {folder}")

    for mountpoint in all_mountpoints:
        if mountpoint.name != "binfmt_misc":
            sandbox.umount2(str(mountpoint), sandbox.MNT_DETACH)


def mount_device_rootfs(chroot_rootfs: Chroot, chroot_base: Chroot = Chroot.native()) -> PurePath:
    """
    Mount the device rootfs.

    :param chroot_rootfs: the chroot where the rootfs that will be
                          installed on the device has been created (e.g.
                          "rootfs_qemu-amd64")
    :param chroot_base: the chroot rootfs mounted to
    :returns: the mountpoint (relative to the chroot)
    """
    mountpoint = PurePath("/mnt", str(chroot_rootfs))
    pmb.helpers.mount.bind(chroot_rootfs.path, chroot_base / mountpoint)
    return mountpoint
