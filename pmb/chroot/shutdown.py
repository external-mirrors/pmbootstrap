# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.helpers import logging

import pmb.chroot
import pmb.helpers.mount
from pmb.core import Chroot
from pmb.core.context import get_context

def shutdown(only_install_related: bool = False) -> None:
    # Remove "in-pmbootstrap" marker from all chroots. This marker indicates
    # that pmbootstrap has set up all mount points etc. to run programs inside
    # the chroots, but we want it gone afterwards (e.g. when the chroot
    # contents get copied to a rootfs / installer image, or if creating an
    # android recovery zip from its contents).
    for marker in get_context().config.work.glob("chroot_*/in-pmbootstrap"):
        pmb.helpers.run.root(["rm", marker])

    logging.debug("Shutdown complete")
