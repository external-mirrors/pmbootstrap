# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os

from pmb.core.pkgrepo import pkgrepo_iglob, pkgrepo_glob_one



def find_path(args, codename, file=''):
    """
    Find path to device APKBUILD under `device/*/device-`.
    :param codename: device codename
    :param file: file to look for (e.g. APKBUILD or deviceinfo), may be empty
    :returns: path to APKBUILD
    """
    return pkgrepo_glob_one(f"device/*/device-{codename}/{file}")

def list_codenames(vendor=None, unmaintained=False):
    """
    Get all devices, for which aports are available
    :param vendor: vendor name to choose devices from, or None for all vendors
    :param unmaintained: include unmaintained devices
    :returns: ["first-device", "second-device", ...]
    """
    ret = []
    for path in pkgrepo_iglob("device/*/device-*"):
        if not unmaintained and '/unmaintained/' in path:
            continue
        device = os.path.basename(path).split("-", 1)[1]
        if (vendor is None) or device.startswith(vendor + '-'):
            ret.append(device)
    return ret


def list_vendors():
    """
    Get all device vendors, for which aports are available
    :returns: {"vendor1", "vendor2", ...}
    """
    ret = set()
    for path in pkgrepo_iglob("device/*/device-*"):
        vendor = os.path.basename(path).split("-", 2)[1]
        ret.add(vendor)
    return ret
