# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pmb.core.context import get_context
from pmb.helpers import logging
import pmb.chroot.apk
import pmb.install
from pmb.core import Chroot


def kernel_flavor_installed(chroot: Chroot, autoinstall: bool = True) -> str | None:
    """
    Get installed kernel flavor. Optionally install the device's kernel
    beforehand.

    :param suffix: the chroot suffix, e.g. "native" or "rootfs_qemu-amd64"
    :param autoinstall: install the device's kernel if it is not installed
    :returns: * string with the installed kernel flavor,
                e.g. ["postmarketos-qcom-sdm845"]
              * None if no kernel is installed
    """
    # Automatically install the selected kernel
    if autoinstall:
        if not chroot.is_mounted():
            pmb.chroot.init(chroot)
        config = get_context().config
        packages = [f"device-{config.device}", *pmb.install.get_kernel_package(config)]
        pmb.chroot.apk.install(packages, chroot)

    glob_result = list((chroot / "usr/share/kernel").glob("*"))

    # There should be only one directory here
    return glob_result[0].name if glob_result else None


def copy_xauthority(chroot: Chroot) -> None:
    """
    Copy the host system's Xauthority file to the pmos user inside the chroot,
    so we can start X11 applications from there.
    """
    # Check $DISPLAY
    logging.info("(native) copy host Xauthority")
    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "Your $DISPLAY variable is not set. If you have an"
            " X11 server running as your current user, try"
            " 'export DISPLAY=:0' and run your last"
            " pmbootstrap command again."
        )

    # Check $XAUTHORITY
    original = os.environ.get("XAUTHORITY")
    if not original:
        original = os.path.join(os.environ["HOME"], ".Xauthority")
    if not os.path.exists(original):
        raise RuntimeError(
            "Could not find your Xauthority file, try to export"
            " your $XAUTHORITY correctly. Looked here: " + original
        )

    # Copy to chroot and chown
    copy = chroot / "home/pmos/.Xauthority"
    if os.path.exists(copy):
        pmb.helpers.run.root(["rm", copy])
    pmb.helpers.run.root(["cp", original, copy])
    pmb.chroot.root(["chown", "pmos:pmos", "/home/pmos/.Xauthority"])


def remove_distfiles_cache(chroot: Chroot) -> None:
    """Remove /var/cache/distfiles from the chroot.

    This is supposed to be created by installing abuild and removed upon
    uninstalling it. However, somehow due to our apk handling this remains
    in built images despite abuild not being installed there—worse, with
    incorrect permissions. So, just remove it manually as to not cause
    problems for people who want to use abuild on postmarketOS."""
    distfiles_dir = chroot / "cache/distfiles"

    if not distfiles_dir.exists():
        return

    pmb.helpers.run.root(["rmdir"], distfiles_dir)
