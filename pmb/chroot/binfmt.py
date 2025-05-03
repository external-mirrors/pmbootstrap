# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pmb.core.arch import Arch
from pmb.core.chroot import Chroot
from pmb.helpers import logging
import pmb.config


def is_registered(arch_qemu: str | Arch) -> bool:
    return os.path.exists(f"{pmb.config.binfmt_misc}/qemu-{arch_qemu}")


# FIXME: Maybe this should use Arch instead of str.
def parse_binfmt_info(arch_qemu: str) -> dict[str, str]:
    # Parse the info file
    full = {}
    info = pmb.config.pmb_src / "pmb/data/qemu-user-binfmt.txt"
    logging.verbose(f"parsing: {info}")
    with open(info) as handle:
        for line in handle:
            if line.startswith("#") or "=" not in line:
                continue
            split = line.split("=")
            key = split[0].strip()
            value = split[1]
            full[key] = value[1:-2]

    ret = {}
    logging.verbose("filtering by architecture: " + arch_qemu)
    for type in ["mask", "magic"]:
        key = arch_qemu + "_" + type
        if key not in full:
            raise RuntimeError(f"Could not find key {key} in binfmt info file: {info}")
        ret[type] = full[key]
    logging.verbose("=> " + str(ret))
    return ret


def register(arch: Arch) -> None:
    """
    Get arch, magic, mask.
    """
    arch_qemu = arch.qemu_user()
    chroot = Chroot.native()

    # always make sure the qemu-<arch> binary is installed, since registering
    # may happen outside of this method (e.g. by OS)
    if f"qemu-{arch_qemu}" not in pmb.chroot.apk.installed(chroot):
        pmb.chroot.init(chroot)
        pmb.chroot.apk.install(["qemu-" + arch_qemu], chroot)

    # Check if we're already registered
    if is_registered(arch_qemu):
        return

    info = parse_binfmt_info(arch_qemu)

    # Build registration string
    # https://en.wikipedia.org/wiki/Binfmt_misc
    # :name:type:offset:magic:mask:interpreter:flags
    name = "qemu-" + arch_qemu
    type = "M"
    offset = ""
    magic = info["magic"]
    mask = info["mask"]

    # FIXME: this relies on a hack where we bind-mount the qemu interpreter into the foreign
    # chroot. This really shouldn't be needed, instead we should unshare pmbootstrap into
    # an Alpine chroot that would have the interpreter installed, then pass the 'F' flag which
    # allows the interpreter to always be run even when we're later in a chroot.
    interpreter = "/usr/bin/qemu-" + arch_qemu + "-static"
    flags = "C"
    code = ":".join(["", name, type, offset, magic, mask, interpreter, flags])

    # Register in binfmt_misc
    logging.info("Register qemu binfmt (" + arch_qemu + ")")
    register = f"{pmb.config.binfmt_misc}/register"
    pmb.helpers.run.root(["sh", "-c", 'echo "' + code + '" > ' + register])
    logging.warning("WARNING: FIXME: binfmt borked because no perms!")


def unregister(arch: Arch) -> None:
    arch_qemu = arch.qemu_user()
    binfmt_file = f"{pmb.config.binfmt_misc}/qemu-" + arch_qemu
    if not os.path.exists(binfmt_file):
        return
    logging.info("Unregister qemu binfmt (" + arch_qemu + ")")
    # pmb.helpers.run.root(["sh", "-c", "echo -1 > " + binfmt_file])
    logging.warning("WARNING: FIXME: binfmt borked because no perms!")
