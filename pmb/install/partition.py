# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from pmb.helpers import logging
import os
import time
import pmb.chroot
import pmb.chroot.apk
import pmb.config
from pmb.core import Chroot
from pmb.types import PartitionLayout
import pmb.core.dps
from functools import lru_cache
from pmb.core.context import get_context
import subprocess


@lru_cache
def get_partition_layout(partition: str, disk: str) -> tuple[int, int]:
    """
    Get the size of a partition in a disk image in bytes
    """
    out = pmb.chroot.root(
        [
            "fdisk",
            "--list-details",
            "--noauto-pt",
            "--sector-size",
            str(get_context().sector_size),
            "--output",
            "Name,Start,End",
            disk,
        ],
        output_return=True,
    ).rstrip()

    start_end: list[str] | None = None
    for line in out.splitlines():
        # FIXME: really ugly matching lmao
        if line.startswith(partition):
            start_end = list(
                filter(lambda x: bool(x), line.replace(f"{partition} ", "").strip().split(" "))
            )
            break
    if not start_end:
        raise ValueError(f"Can't find partition {partition} in {disk}")

    start = int(start_end[0])
    end = int(start_end[1])

    return (start, end)


def partition(layout: PartitionLayout) -> None:
    """
    Partition /dev/install with boot and root partitions

    NOTE: this function modifies "layout" to set the offset properties
    of each partition, these offsets are then used when formatting
    and populating the partitions so that we can access the disk image
    directly without loop mounting.

    :param layout: partition layout from get_partition_layout()
    """
    # Install sgdisk, gptfdisk is also useful for debugging
    pmb.chroot.apk.install(["sgdisk", "gptfdisk"], Chroot.native(), build=False, quiet=True)

    deviceinfo = pmb.parse.deviceinfo()

    # Convert to MB and print info
    logging.info(f"(native) partition /dev/install (boot: {layout.boot.size_mb}M)")

    boot_offset_sectors = deviceinfo.boot_part_start or "2048"
    # For MBR we use to --gpt-to-mbr flag of sgdisk
    # FIXME: test MBR support
    partition_type = deviceinfo.partition_type or "gpt"
    if partition_type == "msdos":
        partition_type = "dos"

    sector_size = get_context().sector_size

    boot_size_sectors = layout.boot.size_sectors(sector_size)
    root_offset_sectors = boot_offset_sectors + boot_size_sectors + 1

    # Align to 2048-sector boundaries (round UP)
    root_offset_sectors = int((root_offset_sectors + 2047) / 2048) * 2048

    arch = str(deviceinfo.arch)
    root_type_guid = pmb.core.dps.root[arch][1]

    proc = subprocess.Popen(
        [
            "chroot",
            os.fspath(Chroot.native().path),
            "sh",
            "-c",
            f"sfdisk --no-tell-kernel --sector-size {sector_size} {layout.path}",
        ],
        stdin=subprocess.PIPE,
    )
    proc.stdin.write(
        (
            f"label: {partition_type}\n"
            f"start={boot_offset_sectors},size={boot_size_sectors},name={layout.boot.partition_label},type=U\n"
            f"start={root_offset_sectors},size=+,name={layout.root.partition_label},type={root_type_guid}\n"
        ).encode()
    )
    proc.stdin.flush()
    proc.stdin.close()
    while proc.poll() is None:
        if proc.stdout is not None:
            print(proc.stdout.readline().decode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError(f"Disk partitioning failed! sfdisk exited with code {proc.returncode}")

    # Configure the partition offsets and final sizes based on sgdisk
    boot_start_sect, _boot_end_sect = get_partition_layout(
        layout.boot.partition_label, "/dev/install"
    )
    root_start_sect, root_end_sect = get_partition_layout(
        layout.root.partition_label, "/dev/install"
    )

    layout.boot.offset = boot_start_sect * sector_size
    layout.root.offset = root_start_sect * sector_size
    layout.root.size = (root_end_sect - root_start_sect) * sector_size


# FIXME: sgdisk?
def partition_cgpt(layout: PartitionLayout, size_boot: int = 0) -> None:
    """
    This function does similar functionality to partition(), but this
    one is for ChromeOS devices which use special GPT. We don't follow
    the Discoverable Partitions Specification here for that exact reason.

    :param layout: partition layout from get_partition_layout()
    :param size_boot: size of the boot partition in MiB
    """

    pmb.chroot.apk.install(["cgpt"], Chroot.native(), build=False)

    deviceinfo = pmb.parse.deviceinfo()

    if deviceinfo.cgpt_kpart_start is None or deviceinfo.cgpt_kpart_size is None:
        raise RuntimeError("cgpt_kpart_start or cgpt_kpart_size not found in deviceinfo")

    cgpt = {
        # or 0 shouldn't be needed since we None check just above, but mypy isn't that smart
        # so we add it to make it happy
        "kpart_start": pmb.parse.deviceinfo().cgpt_kpart_start or "0",
        "kpart_size": pmb.parse.deviceinfo().cgpt_kpart_size or "0",
    }

    # Convert to MB and print info
    mb_boot = f"{size_boot}M"
    logging.info(f"(native) partition /dev/install (boot: {mb_boot})")

    boot_part_start = str(int(cgpt["kpart_start"]) + int(cgpt["kpart_size"]))

    # Convert to sectors
    s_boot = str(int(size_boot * 1024 * 1024 / 512))
    s_root_start = str(int(int(boot_part_start) + int(s_boot)))

    commands = [
        ["parted", "-s", "/dev/install", "mktable", "gpt"],
        ["cgpt", "create", "/dev/install"],
        [
            "cgpt",
            "add",
            "-i",
            str(layout["kernel"]),
            "-t",
            "kernel",
            "-b",
            cgpt["kpart_start"],
            "-s",
            cgpt["kpart_size"],
            "-l",
            "pmOS_kernel",
            "-S",
            "1",  # Successful flag
            "-T",
            "5",  # Tries flag
            "-P",
            "10",  # Priority flag
            "/dev/install",
        ],
        [
            "cgpt",
            "add",
            # pmOS_boot is second partition, the first will be ChromeOS kernel
            # partition
            "-i",
            str(layout["boot"]),  # Partition number
            "-t",
            "efi",  # Mark this partition as bootable for u-boot
            "-b",
            boot_part_start,
            "-s",
            s_boot,
            "-l",
            "pmOS_boot",
            "/dev/install",
        ],
    ]

    dev_size = pmb.chroot.root(["blockdev", "--getsz", "/dev/install"], output_return=True)
    # 33: Sec GPT table (32) + Sec GPT header (1)
    root_size = str(int(dev_size) - int(s_root_start) - 33)

    commands += [
        [
            "cgpt",
            "add",
            "-i",
            str(layout["root"]),
            "-t",
            "data",
            "-b",
            s_root_start,
            "-s",
            root_size,
            "-l",
            "pmOS_root",
            "/dev/install",
        ],
        ["partx", "-a", "/dev/install"],
    ]

    for command in commands:
        pmb.chroot.root(command, check=False)
