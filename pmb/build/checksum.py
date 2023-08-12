# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import hashlib
import os
import fileinput

import pmb.chroot
import pmb.build
import pmb.helpers.run
import pmb.helpers.pmaports

def fix_local(args, pkgname, path=None):
    """
    Fix the checksums of all local sources. Returns True if something was
    changed, False otherwise.

    :param pkgname: name of the package
    :param path: path to the APKBUILD file
    """

    if not path:
        path = os.path.join(pmb.helpers.pmaports.find(args, pkgname, True), "APKBUILD")
    apkbuild = pmb.parse.apkbuild(path)
    checksums = apkbuild["sha512sums"]
    pmaportdir = pmb.helpers.pmaports.find(args, pkgname)
    if not pmaportdir:
        raise RuntimeError("Package '" + pkgname + "': Could not find package!")

    changed = False
    # Use the filename from the checksums, it will be a proper relative path
    # whereas the sources array might have fun subshell stuff in it
    for file in checksums.keys():
        srcpath = os.path.join(pmaportdir, file)
        if not os.path.exists(srcpath):
            continue
        # Maybe some way to optimise this by buffering the file?
        # we aren't dealing with huge files here though
        checksum = hashlib.sha512(open(srcpath, "rb").read()).hexdigest()
        if checksum != checksums[file]:
            logging.info("Fixing checksum for " + srcpath)
            checksums[file] = checksum
            changed = True

    if not changed:
        return False

    with fileinput.input(path, inplace=True) as file:
        in_checksums = False
        for line in file:
            if line.startswith("sha512sums=\""):
                in_checksums = True
            elif in_checksums and line.startswith("\""):
                in_checksums = False
            elif in_checksums:
                _src = line.split(" ")[-1].strip()
                # Is a silent failure here ok?
                if _src in checksums:
                    print(f"{checksums[_src]}  {_src}")
                    continue

            print(line, end="")

    return True

def update(args, pkgname):
    """ Fetch all sources and update the checksums in the APKBUILD. """
    pmb.build.init_abuild_minimal(args)
    pmb.build.copy_to_buildpath(args, pkgname)
    logging.info("(native) generate checksums for " + pkgname)
    pmb.chroot.user(args, ["abuild", "checksum"],
                    working_dir="/home/pmos/build")

    # Copy modified APKBUILD back
    source = args.work + "/chroot_native/home/pmos/build/APKBUILD"
    target = pmb.helpers.pmaports.find(args, pkgname) + "/"
    pmb.helpers.run.user(args, ["cp", source, target])


def verify(args, pkgname):
    """ Fetch all sources and verify their checksums. """
    pmb.build.init_abuild_minimal(args)
    pmb.build.copy_to_buildpath(args, pkgname)
    logging.info("(native) verify checksums for " + pkgname)

    # Fetch and verify sources, "fetch" alone does not verify them:
    # https://github.com/alpinelinux/abuild/pull/86
    pmb.chroot.user(args, ["abuild", "fetch", "verify"],
                    working_dir="/home/pmos/build")
