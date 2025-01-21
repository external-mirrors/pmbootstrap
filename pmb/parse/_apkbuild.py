# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# mypy: disable-error-code="attr-defined"
from pmb.core.context import get_context
from pmb.helpers import logging
from pmb.types import Apkbuild
import os
from pathlib import Path
import json

import pmb.config
from pmb.meta import Cache
import pmb.helpers.devices
import pmb.parse.version

from pmb.core.sandbox import ChrootSandbox
from pmb.core.chroot import Chroot
from pmb.helpers import xhash


def parse_to_json(path: Path) -> Apkbuild:
    cache_dir = get_context().config.work / "cache_apkbuild"
    cache_file = cache_dir / f"{xhash(str(path))}.json"
    # If we have a JSON cache with a newer mtime we're good to go!
    if cache_file.exists() and cache_file.stat().st_mtime > path.stat().st_mtime:
        # logging.info(f"Loaded from cache: {path}")
        return Apkbuild.fromJSON(cache_file.open().read())

    sandbox = ChrootSandbox(Chroot.native(), name="apkbuild_parse")\
        .bind(pmb.config.pmb_src / "pmb/data/parse-pkg.sh", "/work/parse-pkg.sh")\
        .bind(path, "/work/APKBUILD")\
        .with_packages(["jq"])\
        .build()

    json_data = sandbox.run(["sh", "-c", "/work/parse-pkg.sh /work/APKBUILD"])
    try:
        out = json.loads(json_data)
    except json.decoder.JSONDecodeError as e:
        raise RuntimeError(f"{json_data}\nFailed to parse package {path}: {e}")

    apkbuild = Apkbuild(subpkg=False)
    for key, val in out.items():
        # print(f"got {key}: {val}")
        if key == "subpackages":
            continue
        if key.startswith("_pmb_"):
            key = key[1:]
        if key in apkbuild.__dict__.keys():
            setattr(apkbuild, key, val)

    for subpkgname, content in out.get("subpackages", {}).items():
        subpkg = Apkbuild(subpkg=True)
        for key, val in content.items():
            setattr(subpkg, key, val)
        apkbuild.subpackages[subpkgname] = subpkg

    # Save the apkbuild to the cache as JSON
    cache_dir.mkdir(exist_ok=True)
    cache_file.open("w").write(apkbuild.toJSON())
    return apkbuild


@Cache("path")
def apkbuild(path: Path, check_pkgver: bool = True, check_pkgname: bool = True) -> Apkbuild:
    """
    Parse relevant information out of the APKBUILD file. This is not meant
    to be perfect and catch every edge case (for that, a full shell parser
    would be necessary!). Instead, it should just work with the use-cases
    covered by pmbootstrap and not take too long.
    Run 'pmbootstrap apkbuild_parse hello-world' for a full output example.

    :param path: full path to the APKBUILD
    :param check_pkgver: verify that the pkgver is valid.
    :param check_pkgname: the pkgname must match the name of the aport folder
    :returns: relevant variables from the APKBUILD. Arrays get returned as
              arrays.
    """
    if path.name != "APKBUILD":
        path = path / "APKBUILD"

    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found!")

    # Read the file and check line endings
    ret = parse_to_json(path)

    # Sanity check: pkgname
    suffix = f"/{ret.pkgname}/APKBUILD"
    if check_pkgname:
        if not os.path.realpath(path).endswith(suffix):
            logging.info(f"Folder: '{os.path.dirname(path)}'")
            logging.info(f"Pkgname: '{ret.pkgname}'")
            raise RuntimeError(
                "The pkgname must be equal to the name of the folder that contains the APKBUILD!"
            )

    # Sanity check: pkgver
    if check_pkgver:
        if not pmb.parse.version.validate(ret.pkgver):
            logging.info(
                "NOTE: Valid pkgvers are described here: "
                "https://wiki.alpinelinux.org/wiki/APKBUILD_Reference#pkgver"
            )
            raise RuntimeError(f"Invalid pkgver '{ret.pkgver}' in APKBUILD: {path}")

    # Fill cache
    return ret


def kernels(device: str) -> dict[str, str] | None:
    """
    Get the possible kernels from a device-* APKBUILD.

    :param device: the device name, e.g. "lg-mako"
    :returns: None when the kernel is hardcoded in depends
    :returns: kernel types and their description (as read from the subpackages)
              possible types: "downstream", "stable", "mainline"
              example: {"mainline": "Mainline description", "downstream": "Downstream description"}
    """
    # Read the APKBUILD
    apkbuild_path = pmb.helpers.devices.find_path(device, "APKBUILD")
    if apkbuild_path is None:
        return None
    subpackages = apkbuild(apkbuild_path).subpackages

    # Read kernels from subpackages
    ret = {}
    subpackage_prefix = f"device-{device}-kernel-"
    for subpkgname, subpkg in subpackages.items():
        if not subpkgname.startswith(subpackage_prefix):
            continue
        if subpkg is None:
            raise RuntimeError(f"Cannot find subpackage function for: {subpkgname}")
        name = subpkgname[len(subpackage_prefix) :]
        ret[name] = subpkg.pkgdesc

    # Return
    if ret:
        return ret
    return None


def read_file(path: Path):
    """
    Read an APKBUILD file

    :param path: full path to the APKBUILD
    :returns: contents of an APKBUILD as a list of strings
    """
    with path.open(encoding="utf-8") as handle:
        lines = handle.readlines()
        if handle.newlines != "\n":
            raise RuntimeError(f"Wrong line endings in APKBUILD: {path}")
    return lines


def _parse_comment_tags(lines: list[str], tag: str) -> list[str]:
    """
    Parse tags defined as comments in a APKBUILD file. This can be used to
    parse e.g. the maintainers of a package (defined using # Maintainer:).

    :param lines: lines of the APKBUILD
    :param tag: the tag to parse, e.g. Maintainer
    :returns: array of values of the tag, one per line
    """
    prefix = f"# {tag}:"
    ret = []
    for line in lines:
        if line.startswith(prefix):
            ret.append(line[len(prefix) :].strip())
    return ret


def maintainers(path: Path) -> list[str] | None:
    """
    Parse maintainers of an APKBUILD file. They should be defined using
    # Maintainer: (first maintainer) and # Co-Maintainer: (additional
    maintainers).

    :param path: full path to the APKBUILD
    :returns: array of (at least one) maintainer, or None
    """
    lines = read_file(path)
    maintainers = _parse_comment_tags(lines, "Maintainer")
    if not maintainers:
        return None

    # An APKBUILD should only have one Maintainer:,
    # in pmaports others should be defined using Co-Maintainer:
    if len(maintainers) > 1:
        raise RuntimeError("Multiple Maintainer: lines in APKBUILD")

    maintainers += _parse_comment_tags(lines, "Co-Maintainer")
    if "" in maintainers:
        raise RuntimeError("Empty (Co-)Maintainer: tag")
    return maintainers


def archived(path: Path) -> str | None:
    """
    Return if (and why) an APKBUILD might be archived. This should be
    defined using a # Archived: <reason> tag in the APKBUILD.

    :param path: full path to the APKBUILD
    :returns: reason why APKBUILD is archived, or None
    """
    archived = _parse_comment_tags(read_file(path), "Archived")
    if not archived:
        return None
    return "\n".join(archived)
