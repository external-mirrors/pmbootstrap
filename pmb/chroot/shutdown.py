# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.core.arch import Arch
from pmb.helpers import logging
import socket
from contextlib import closing

import pmb.chroot
import pmb.helpers.mount
from pmb.core import Chroot, ChrootType
from pmb.core.context import get_context


def kill_adb() -> None:
    """
    Kill adb daemon if it's running.
    """
    port = 5038
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            pmb.chroot.root(["adb", "-P", str(port), "kill-server"])


def kill_sccache() -> None:
    """
    Kill sccache daemon if it's running. Unlike ccache it automatically spawns
    a daemon when you call it and exits after some time of inactivity.
    """
    port = 4226
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            pmb.chroot.root(["sccache", "--stop-server"])


def shutdown_cryptsetup_device(name: str) -> None:
    """
    :param name: cryptsetup device name, usually "pm_crypt" in pmbootstrap
    """
    if not (Chroot.native() / "dev/mapper" / name).exists():
        return
    pmb.chroot.apk.install(["cryptsetup"], Chroot.native())
    status = pmb.chroot.root(["cryptsetup", "status", name], output_return=True, check=False)
    if not status:
        logging.warning(
            "WARNING: Failed to run cryptsetup to get the status"
            " for " + name + ", assuming it is not mounted"
            " (shutdown fails later if it is)!"
        )
        return

    if status.startswith("/dev/mapper/" + name + " is active."):
        pmb.chroot.root(["cryptsetup", "luksClose", name])
    elif status.startswith("/dev/mapper/" + name + " is inactive."):
        # When "cryptsetup status" fails, the device is not mounted and we
        # have a left over file (#83)
        pmb.chroot.root(["rm", "/dev/mapper/" + name])
    else:
        raise RuntimeError("Failed to parse 'cryptsetup status' output!")


def shutdown(only_install_related: bool = False) -> None:
    # Stop daemons
    kill_adb()
    kill_sccache()

    # Umount installation-related paths (order is important!)
    # pmb.helpers.mount.umount_all(chroot / "mnt/install")
    shutdown_cryptsetup_device("pm_crypt")

    # Remove "in-pmbootstrap" marker from all chroots. This marker indicates
    # that pmbootstrap has set up all mount points etc. to run programs inside
    # the chroots, but we want it gone afterwards (e.g. when the chroot
    # contents get copied to a rootfs / installer image, or if creating an
    # android recovery zip from its contents).
    for marker in get_context().config.localdir.glob("chroot_*/in-pmbootstrap"):
        pmb.helpers.run.root(["rm", marker])

    logging.debug("Shutdown complete")
