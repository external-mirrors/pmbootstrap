# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

import pmb.config
import pmb.chroot.apk
from pmb.core.pkgrepo import pkgrepo_glob_one

def list_chroot(args, suffix, remove_prefix=True):
    ret = []
    prefix = pmb.config.initfs_hook_prefix
    for pkgname in pmb.chroot.apk.installed(args, suffix).keys():
        if pkgname.startswith(prefix):
            if remove_prefix:
                ret.append(pkgname[len(prefix):])
            else:
                ret.append(pkgname)
    return ret


def ls(args, suffix):
    hooks_chroot = list_chroot(args, suffix)
    hooks_aports = pkgrepo_glob_one(f"*/{pmb.config.initfs_hook_prefix}*")

    for hook in hooks_aports:
        line = f"* {hook} ({'' if hook in hooks_chroot else 'not '}installed)"
        logging.info(line)


def add(args, hook, suffix):
    prefix = pmb.config.initfs_hook_prefix
    if hook not in pkgrepo_glob_one(f"*/{prefix}*"):
        raise RuntimeError("Invalid hook name!"
                           " Run 'pmbootstrap initfs hook_ls'"
                           " to get a list of all hooks.")
    pmb.chroot.apk.install(args, [f"{prefix}{hook}"], suffix)


def delete(args, hook, suffix):
    prefix = pmb.config.initfs_hook_prefix
    if hook not in pkgrepo_glob_one(f"*/{prefix}*"):
        raise RuntimeError("There is no such hook installed!")
    pmb.chroot.root(args, ["apk", "del", f"{prefix}{hook}"], suffix)


def update(args, suffix):
    """
    Rebuild and update all hooks that are out of date
    """
    pmb.chroot.apk.install(args, list_chroot(args, suffix, False), suffix)
