# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.helpers import logging
import os
from pathlib import Path
from pmb.types import PmbArgs, PartitionLayout
import pmb.helpers.mount
import pmb.helpers.cli
import pmb.helpers.run
import pmb.config
from pmb.core import Chroot
from pmb.core.context import get_context


def previous_install(path: Path) -> bool:
    """
    Search the disk for possible existence of a previous installation of
    pmOS. We temporarily mount the possible pmOS_boot partition as
    /dev/diskp1 inside the native chroot to check the label from there.
    :param path: path to disk block device (e.g. /dev/mmcblk0)
    """
    label = ""
    for blockdevice_outside in [path.with_stem(f"{path.name}1"), path.with_stem(f"{path.name}p1")]:
        if not os.path.exists(blockdevice_outside):
            continue
        blockdevice_inside = "/dev/diskp1"
        pmb.helpers.mount.bind_file(blockdevice_outside, Chroot.native() / blockdevice_inside)
        try:
            label = pmb.chroot.root(
                ["blkid", "-s", "LABEL", "-o", "value", blockdevice_inside], output_return=True
            )
        except RuntimeError:
            logging.info(
                "WARNING: Could not get block device label,"
                " assume no previous installation on that partition"
            )

        pmb.helpers.run.root(["umount", Chroot.native() / blockdevice_inside])
    return "pmOS_boot" in label


def mount_disk(path: Path) -> None:
    """
    :param path: path to disk block device (e.g. /dev/mmcblk0)
    """
    # Sanity checks
    if not os.path.exists(path):
        raise RuntimeError(f"The disk block device does not exist: {path}")
    for path_mount in path.parent.glob(f"{path.name}*"):
        if pmb.helpers.mount.ismount(path_mount):
            raise RuntimeError(f"{path_mount} is mounted! Will not attempt to format this!")
    logging.info(f"(native) mount /dev/install (host: {path})")
    pmb.helpers.mount.bind_file(path, Chroot.native() / "dev/install")
    if previous_install(path):
        if not pmb.helpers.cli.confirm(
            "WARNING: This device has a previous installation of pmOS. CONTINUE?"
        ):
            raise RuntimeError("Aborted.")
    else:
        if not pmb.helpers.cli.confirm(f"EVERYTHING ON {path} WILL BE ERASED! CONTINUE?"):
            raise RuntimeError("Aborted.")


def create_and_mount_image(
    args: PmbArgs,
    layout: PartitionLayout,
    split: bool = False,
) -> None:
    """
    Create a new image file, and mount it as /dev/install.

    :param size_boot: size of the boot partition in bytes
    :param size_root: size of the root partition in bytes
    :param split: create separate images for boot and root partitions
    """

    # Short variables for paths
    chroot = Chroot.native()
    config = get_context().config
    img_path_prefix = chroot / "home/pmos/rootfs"
    img_path_full = img_path_prefix / f"{config.device}.img"
    img_path_boot = img_path_prefix / f"{config.device}-boot.img"
    img_path_root = img_path_prefix / f"{config.device}-root.img"

    # Umount and delete existing images
    for img_path in [img_path_full, img_path_boot, img_path_root]:
        outside = chroot / img_path
        if os.path.exists(outside):
            pmb.helpers.mount.umount_all(chroot / "mnt")
            pmb.chroot.root(["rm", img_path])

    # Make sure there is enough free space
    size_full = round(layout.boot.size + layout.root.size)
    disk_data = os.statvfs(get_context().config.cache)
    free = disk_data.f_bsize * disk_data.f_bavail
    if size_full > free:
        raise RuntimeError(
            f"Not enough free space to create rootfs image! (free: {round(free / (1024**2))}M, required: {round(size_full / (1024**2))}M)"
        )

    # Create empty image files
    rootfs_dir = chroot / "home/pmos/rootfs"
    rootfs_dir.mkdir(exist_ok=True)
    os.chown(rootfs_dir, int(pmb.config.chroot_uid_user), int(pmb.config.chroot_uid_user))
    if split:
        images = {img_path_boot: layout.boot.size, img_path_root: layout.root.size}
    else:
        # Account for the partition table
        size_full += pmb.parse.deviceinfo().boot_part_start * pmb.config.block_size
        # Add 4 sectors for alignment and the backup header
        size_full += pmb.config.block_size * 4
        # Round to sector size
        size_full = int((size_full + 512) / pmb.config.block_size) * pmb.config.block_size
        images = {img_path_full: size_full}

    for img_path, image_size in images.items():
        img_path.unlink(missing_ok=True)
        logging.info(f"(native) create {img_path.name} ({round(image_size / (1024**2))}M)")
        pmb.helpers.run.user(["truncate", "-s", f"{image_size}", f"{img_path}"])
        os.chown(img_path, int(pmb.config.chroot_uid_user), int(pmb.config.chroot_uid_user))
        # pmb.helpers.run.root(["dd", "if=/dev/zero", f"of={img_path}", f"bs={image_size}", "count=1"])

    # Mount to /dev/install
    if not split:
        layout.boot.path = layout.root.path = layout.path = "/dev/install"
        mount_image_paths = {img_path_full: layout.path}
    else:
        layout.boot.path = "/dev/installp1"
        layout.root.path = "/dev/installp2"
        mount_image_paths = {img_path_boot: layout.boot.path, img_path_root: layout.root.path}

    for img_path, mount_point in mount_image_paths.items():
        # logging.info(f"(native) mount {mount_point} ({img_path.name})")
        pmb.helpers.mount.bind_file(img_path, chroot / mount_point)


def create(args: PmbArgs, layout: PartitionLayout, split: bool, disk: Path | None) -> None:
    """
    Create /dev/install (the "install blockdevice").

    :param size_boot: size of the boot partition in MiB
    :param size_root: size of the root partition in MiB
    :param split: create separate images for boot and root partitions
    :param disk: path to disk block device (e.g. /dev/mmcblk0) or None
    """
    pmb.helpers.mount.umount_all(Chroot.native() / "dev/install")
    if disk:
        mount_disk(disk)
    else:
        create_and_mount_image(args, layout, split)
