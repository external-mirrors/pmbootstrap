# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
from pmb.core.context import get_context
from pmb.helpers import logging
import time

from pmb.types import PathString
import pmb.helpers.mount
import pmb.helpers.run
import pmb.chroot
from pmb.core import Chroot


def init() -> None:
    if not Path("/sys/module/loop").is_dir():
        pmb.helpers.run.root(["modprobe", "loop"])
    for loopdevice in Path("/dev/").glob("loop*"):
        if loopdevice.is_dir() or loopdevice.name == "loop-control":
            continue
        Chroot.native().bind_file(loopdevice, loopdevice)
        # pmb.helpers.mount.bind_file(loopdevice, Chroot.native() / loopdevice)


def mount(img_path: Path, _sector_size: int | None = None) -> Path:
    """
    :param img_path: Path to the img file inside native chroot.
    """
    logging.debug(f"(native) mount {img_path} (loop)")

    # Try to mount multiple times (let the kernel module initialize #1594)
    for i in range(0, 5):
        # Retry
        if i > 0:
            logging.debug("loop module might not be initialized yet, retry in" " one second...")
            time.sleep(1)

        # Mount and return on success
        init()

        sector_size = None
        if _sector_size:
            sector_size = str(_sector_size)
        sector_size = sector_size or pmb.parse.deviceinfo().rootfs_image_sector_size

        losetup_cmd: list[PathString] = ["losetup", "-f", img_path]
        if sector_size:
            losetup_cmd += ["-b", str(int(sector_size))]

        pmb.helpers.run.root(losetup_cmd, check=False)

        loopdevice: Path
        try:
            loopdevice = device_by_back_file(img_path)
        except RuntimeError as e:
            if i == 4:
                raise e
            pass

        # Let the user running pmbootstrap access the loop device
        # FIXME: insecure?? Need a way to change it back too...
        pmb.helpers.run.root(["chown", f"{os.getuid()}:{os.getgid()}", loopdevice])

        return loopdevice
    raise AssertionError("This should never be reached")


def device_by_back_file(back_file: Path) -> Path:
    """
    Get the /dev/loopX device that points to a specific image file.
    """

    # Get list from losetup
    losetup_output = pmb.helpers.run.user_output(["losetup", "--json", "--list"])
    if not losetup_output:
        raise RuntimeError("losetup failed")

    # Find the back_file
    losetup = json.loads(losetup_output)
    for loopdevice in losetup["loopdevices"]:
        if loopdevice["back-file"] is not None and Path(loopdevice["back-file"]) == back_file:
            return Path(loopdevice["name"])
    raise RuntimeError(f"Failed to find loop device for {back_file}")


def umount(img_path: Path) -> None:
    """
    :param img_path: Path to the img file inside native chroot.
    """
    device: Path
    try:
        device = device_by_back_file(img_path)
    except RuntimeError:
        return
    logging.debug(f"(native) umount {device}")
    pmb.chroot.root(["losetup", "-d", device])


def detach_all(silent=False) -> None:
    """
    Detach all loop devices used by pmbootstrap
    """
    losetup_output = pmb.helpers.run.user(
        ["losetup", "--json", "--list"], output_return=True, output="null" if silent else "log"
    )
    if not losetup_output:
        return
    losetup = json.loads(str(losetup_output))
    work = get_context().config.work
    for loopdevice in losetup["loopdevices"]:
        if Path(loopdevice["back-file"]).is_relative_to(work):
            pmb.helpers.run.root(["kpartx", "-d", loopdevice["name"]], check=False)
            pmb.helpers.run.root(["losetup", "-d", loopdevice["name"]])
            # FIXE: uhh this is probably not universal
            pmb.helpers.run.root(["chown", "root:disk", loopdevice["name"]])
    return
