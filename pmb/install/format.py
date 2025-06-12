# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.core.context import get_context
from pmb.helpers import logging
from pmb.helpers.devices import get_device_category_by_name
import pmb.chroot
import pmb.chroot.apk
import pmb.parse
from pmb.core import Chroot
from pmb.core.context import get_context
from pmb.types import PartitionLayout, PmbArgs, PathString, RunOutputTypeDefault
import os
from pathlib import Path


def install_fsprogs(filesystem: str) -> None:
    """Install the package required to format a specific filesystem."""
    fsprogs = pmb.config.filesystems.get(filesystem)
    if not fsprogs:
        raise RuntimeError(f"Unsupported filesystem: {filesystem}")
    pmb.chroot.apk.install([fsprogs], Chroot.native())


def format_and_mount_boot(layout: PartitionLayout) -> None:
    """
    :param device: boot partition on install block device (e.g. /dev/installp1)

    When adjusting this function, make sure to also adjust
    ondev-prepare-internal-storage.sh in postmarketos-ondev.git!
    """
    pmb.chroot.apk.install(["mtools"], Chroot.native(), build=False, quiet=True)
    deviceinfo = pmb.parse.deviceinfo()
    filesystem = deviceinfo.boot_filesystem or "ext2"
    layout.boot.filesystem = filesystem
    sector_size = get_context().sector_size
    offset_sectors = deviceinfo.boot_part_start
    offset_bytes = layout.boot.offset
    boot_path = "/mnt/rootfs/boot"
    install_fsprogs(filesystem)
    logging.info(f"(native) format {layout.boot.path} (boot, {filesystem})")
    # mkfs.fat takes offset in sectors! wtf...
    if filesystem == "fat16":
        pmb.chroot.root(
            [
                "mkfs.fat",
                "-F",
                "16",
                "-i",
                layout.boot.uuid.replace("-", ""),
                "-S",
                str(sector_size),
                "--offset",
                str(offset_sectors),
                "-n",
                layout.boot.partition_label,
                layout.boot.path,
            ]
        )
    elif filesystem == "fat32":
        pmb.chroot.root(
            [
                "mkfs.fat",
                "-F",
                "32",
                "-i",
                layout.boot.uuid.replace("-", ""),
                "-S",
                str(sector_size),
                "--offset",
                str(offset_sectors),
                "-n",
                layout.boot.partition_label,
                layout.boot.path,
            ]
        )
    elif filesystem == "ext2":
        pmb.chroot.root(
            [
                "mkfs.ext2",
                "-d",
                boot_path,
                "-U",
                layout.boot.uuid,
                "-F",
                "-q",
                "-E",
                f"offset={offset_bytes}",
                "-L",
                layout.boot.partition_label,
                layout.boot.path,
                f"{round(layout.boot.size / 1024)}k",
            ]
        )
    elif filesystem == "btrfs":
        raise ValueError("BTRFS not yet supported with new sandbox")
        pmb.chroot.root(
            ["mkfs.btrfs", "-f", "-q", "-L", layout.boot.partition_label, layout.boot.path]
        )
    else:
        raise RuntimeError("Filesystem " + filesystem + " is not supported!")

    # Copy in the filesystem
    if filesystem.startswith("fat"):
        contents = [
            path.relative_to(Chroot.native().path)
            for path in (Chroot.native() / boot_path).glob("*")
        ]
        pmb.chroot.root(
            ["mcopy", "-i", f"{layout.boot.path}@@{offset_bytes}", "-s", *contents, "::"]
        )


def format_luks_root(args: PmbArgs, layout: PartitionLayout) -> None:
    """
    :param device: root partition on install block device (e.g. /dev/installp2)
    """
    device = layout.path

    logging.info("(native) Encrypting root filesystem!")
    if not os.environ.get("PMB_FDE_PASSWORD", None):
        logging.info(" *** TYPE IN THE FULL DISK ENCRYPTION PASSWORD (TWICE!) ***")

    # Avoid cryptsetup warning about missing locking directory
    pmb.chroot.root(["mkdir", "-p", "/run/cryptsetup"])

    # FIXME: this /should/ work but we get:
    # Device /dev/install contains broken LUKS metadata. Aborting operation.
    # sooo
    format_cmd = [
        "cryptsetup",
        "reencrypt",
        "-q",
        "--encrypt",
        "--cipher",
        args.cipher,
        "--iter-time",
        args.iter_time,
        "--use-random",
        "--reduce-device-size",
        "32M",
        "--force-offline-reencrypt",
        "--offset",
        str(layout.root.offset_sectors(512)),
        device,
    ]

    path_outside = None
    fde_key = os.environ.get("PMB_FDE_PASSWORD", None)
    if fde_key:
        # Write passphrase to a temp file, to avoid printing it in any log
        path_outside = Chroot.native() / "tmp/fde_key"
        with open(path_outside, "w", encoding="utf-8") as handle:
            handle.write(f"{fde_key}")
        format_cmd += [str(path_outside.relative_to(Chroot.native().path))]

    try:
        pmb.chroot.root(format_cmd, output=RunOutputTypeDefault.INTERACTIVE)
    finally:
        if path_outside:
            os.unlink(path_outside)


def prepare_btrfs_subvolumes(args: PmbArgs, device: str, mountpoint: str) -> None:
    """
    Create separate subvolumes if root filesystem is btrfs.
    This lets us do snapshots and rollbacks of relevant parts
    of the filesystem.
    /var contains logs, VMs, containers, flatpaks; and shouldn't roll back,
    /root is root's home directory and shouldn't roll back,
    /tmp has temporary files, snapshotting them is unnecessary,
    /srv contains data for web and FTP servers, and shouldn't roll back,
    /snapshots should be a separate subvol so that changing the root subvol
    doesn't affect snapshots
    """
    subvolume_list = ["@", "@home", "@root", "@snapshots", "@srv", "@tmp", "@var"]

    for subvolume in subvolume_list:
        pmb.chroot.root(["btrfs", "subvol", "create", f"{mountpoint}/{subvolume}"])

    # Set the default root subvolume to be separate from top level btrfs
    # subvol. This lets us easily swap out current root subvol with an
    # earlier snapshot.
    pmb.chroot.root(["btrfs", "subvol", "set-default", f"{mountpoint}/@"])

    # Make directories to mount subvols onto
    pmb.chroot.root(["umount", mountpoint])
    pmb.chroot.root(["mount", device, mountpoint])
    pmb.chroot.root(
        [
            "mkdir",
            f"{mountpoint}/home",
            f"{mountpoint}/root",
            f"{mountpoint}/.snapshots",
            f"{mountpoint}/srv",
            f"{mountpoint}/var",
        ]
    )

    # snapshots contain sensitive information,
    # and should only be readable by root.
    pmb.chroot.root(["chmod", "700", f"{mountpoint}/root"])
    pmb.chroot.root(["chmod", "700", f"{mountpoint}/.snapshots"])

    # Mount subvols
    pmb.chroot.root(["mount", "-o", "subvol=@var", device, f"{mountpoint}/var"])
    pmb.chroot.root(["mount", "-o", "subvol=@home", device, f"{mountpoint}/home"])
    pmb.chroot.root(["mount", "-o", "subvol=@root", device, f"{mountpoint}/root"])
    pmb.chroot.root(["mount", "-o", "subvol=@srv", device, f"{mountpoint}/srv"])
    pmb.chroot.root(["mount", "-o", "subvol=@snapshots", device, f"{mountpoint}/.snapshots"])

    # Disable CoW for /var, to avoid write multiplication
    # and slowdown on databases, containers and VM images.
    pmb.chroot.root(["chattr", "+C", f"{mountpoint}/var"])


def format_and_mount_root(args: PmbArgs, layout: PartitionLayout) -> None:
    """
    :param layout: disk image layout
    """
    # Format
    if not args.rsync:
        filesystem = layout.root.filesystem
        layout.root.filesystem = filesystem
        rootfs = Path("/mnt/rootfs")

        # Bind mount an empty path over /boot so we don't include it in the root partition
        # FIXME: better way to check if running with --single-partition
        if len(layout) > 1:
            empty_dir = Path("/tmp/empty")
            pmb.mount.bind(empty_dir, Chroot.native() / rootfs / "boot")

        if filesystem != "ext4":
            raise RuntimeError(
                "Only EXT4 supports offset parameter for writing directly to disk image!"
            )

        if filesystem == "ext4":
            device_category = get_device_category_by_name(get_context().config.device)

            if device_category.allows_downstream_ports():
                # Some downstream kernels don't support metadata_csum (#1364).
                # When changing the options of mkfs.ext4, also change them in the
                # recovery zip code (see 'grep -r mkfs\.ext4')!
                category_opts = ["-O", "^metadata_csum"]
            else:
                category_opts = []
            # Some downstream kernels don't support metadata_csum (#1364).
            # When changing the options of mkfs.ext4, also change them in the
            # recovery zip code (see 'grep -r mkfs\.ext4')!
            mkfs_root_args = [
                "mkfs.ext4",
                "-d",
                rootfs,
                "-F",
                "-q",
                "-L",
                layout.root.partition_label,
                "-U",
                layout.root.uuid,
                *category_opts,
            ]
            # pmb#2568: tell mkfs.ext4 to make a filesystem with enough
            # indoes that we don't run into "out of space" errors
            mkfs_root_args = [*mkfs_root_args, "-i", "16384"]
            if not layout.split:
                mkfs_root_args = [*mkfs_root_args, "-E", f"offset={layout.root.offset}"]
        elif filesystem == "f2fs":
            mkfs_root_args = ["mkfs.f2fs", "-f", "-l", layout.root.partition_label]
        elif filesystem == "btrfs":
            mkfs_root_args = ["mkfs.btrfs", "-f", "-L", layout.root.partition_label]
        else:
            raise RuntimeError(f"Don't know how to format {filesystem}!")

        install_fsprogs(filesystem)
        logging.info(f"(native) format {layout.root.path} (root, {filesystem})")
        rootfs_size = round(layout.root.size / 1024)
        # Leave some empty space for LUKS
        if layout.fde:
            rootfs_size -= 64 * 1024
        pmb.chroot.root([*mkfs_root_args, layout.root.path, f"{round(layout.root.size / 1024)}k"])

        # Unmount the empty dir we mounted over /boot
        pmb.mount.umount_all(Chroot.native() / rootfs / "boot")

    # FIXME: btrfs borked
    # if not args.rsync and filesystem == "btrfs":
    #     # Make flat btrfs subvolume layout
    #     prepare_btrfs_subvolumes(args, device, mountpoint)


def format(
    args: PmbArgs,
    layout: PartitionLayout | None,
    rootfs: Path,
    disk: PathString | None,
) -> None:
    """
    :param layout: partition layout from get_partition_layout() or None
    :param boot_label: label of the boot partition (e.g. "pmOS_boot")
    :param root_label: label of the root partition (e.g. "pmOS_root")
    :param disk: path to disk block device (e.g. /dev/mmcblk0) or None
    """
    # FIXME: do this elsewhere?
    pmb.mount.bind(rootfs, Chroot.native().path / "mnt/rootfs")

    # FIXME: probably broken because luksOpen uses loop under the hood, needs testing...
    # root_dev = "/dev/mapper/pm_crypt"

    format_and_mount_root(args, layout)
    # FIXME: better way to check if we are running with --single-partition
    if len(layout) > 1:
        format_and_mount_boot(layout)

    if args.full_disk_encryption:
        format_luks_root(args, layout)
