# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import pmb.chroot.run
from pmb.meta import Cache
from pmb.helpers import logging
import os
import shutil

import pmb.chroot
import pmb.chroot.mount
import pmb.chroot.zap
import pmb.config
import pmb.config.workdir
import pmb.helpers.apk_static
import pmb.helpers.apk
import pmb.helpers.repo
import pmb.helpers.run
from pmb.core import Chroot, ChrootType
from pmb.core.context import get_context
from pmb.types import PathString


def copy_resolv_conf(chroot: Chroot) -> None:
    """
    Use pythons super fast file compare function (due to caching)
    and copy the /etc/resolv.conf to the chroot, in case it is
    different from the host.
    If the file doesn't exist, create an empty file with 'touch'.
    """
    host = "/etc/resolv.conf"
    resolv_path = chroot / host
    if os.path.exists(host):
        shutil.copy(host, resolv_path)
    else:
        pmb.helpers.run.root(["touch", resolv_path])


def mark_in_chroot(chroot: Chroot = Chroot.native()) -> None:
    """
    Touch a flag so we can know when we're running in chroot (and
    don't accidentally flash partitions on our host). This marker
    gets removed in pmb.chroot.shutdown (pmbootstrap shutdown).
    """
    in_chroot_file = chroot / "in-pmbootstrap"
    if not in_chroot_file.exists():
        pmb.helpers.run.root(["touch", in_chroot_file])


def init_keys(chroot: Chroot) -> None:
    """
    All Alpine and postmarketOS repository keys are shipped with pmbootstrap.
    Copy them into $WORK/keys, which gets mounted inside the various
    chroots as /etc/apk/keys.

    This is done before installing any package, so apk can verify APKINDEX
    files of binary repositories even though alpine-keys/postmarketos-keys are
    not installed yet.
    """
    target = chroot / "etc/apk/keys/"
    target.mkdir(exist_ok=True, parents=True)
    for key in pmb.config.apk_keys_path.glob("*.pub"):
        shutil.copy(key, target)
    for key in (get_context().config.cache / "keys").glob("*.pub"):
        shutil.copy(key, target)


@Cache()
def warn_if_chroots_outdated() -> None:
    outdated = pmb.config.workdir.chroots_outdated()
    if outdated:
        days_warn = int(pmb.config.chroot_outdated / 3600 / 24)
        msg = ""
        if Chroot.native() in outdated:
            msg += "your native"
            if Chroot.rootfs(get_context().config.device) in outdated:
                msg += " and rootfs chroots are"
            else:
                msg += " chroot is"
        elif Chroot.rootfs(get_context().config.device) in outdated:
            msg += "your rootfs chroot is"
        else:
            msg += "some of your chroots are"
        logging.warning(
            f"WARNING: {msg} older than {days_warn} days. Consider running 'pmbootstrap zap'."
        )


def setup_cache_path(chroot: Chroot):
    # Set up the apk cache to point to the working cache
    cache_target = chroot / "etc/apk/cache"
    if not cache_target.is_symlink():
        cache_target.parent.mkdir(parents=True, exist_ok=True)
        cache_target.symlink_to(f"/cache/apk_{chroot.arch}")


def init(chroot: Chroot) -> None:
    """
    Initialize a chroot by copying the resolv.conf and updating
    /etc/apk/repositories. If /bin/sh is missing, create the chroot from
    scratch.
    """
    # When already initialized: just prepare the chroot
    arch = chroot.arch

    # If the channel is wrong and the user has auto_zap_misconfigured_chroots
    # enabled, zap the chroot and reinitialize it
    if chroot.exists():
        zap = pmb.config.workdir.chroot_check_channel(chroot)
        if zap:
            pmb.chroot.zap.del_chroot(chroot.path, confirm=False)
            pmb.config.workdir.clean()
        if pmb.helpers.file.is_older_than(chroot / "etc/apk/repositories", 300):
            pmb.helpers.apk.update_repository_list(chroot.path)
            warn_if_chroots_outdated()

    pmb.chroot.mount.mount(chroot)
    logging.info(f"({chroot}) Mounted!")
    mark_in_chroot(chroot)
    setup_cache_path(chroot)
    copy_resolv_conf(chroot)
    if chroot.exists():
        return

    # Fetch apk.static
    pmb.helpers.apk_static.init()

    logging.info(f"({chroot}) Creating chroot")

    # Initialize /etc/apk/keys/, resolv.conf, repositories
    init_keys(chroot)
    # Also creates /etc
    pmb.helpers.apk.update_repository_list(chroot.path)

    pmb.config.workdir.chroot_save_init(chroot)

    pmb.helpers.repo.update(arch)
    # Create the /usr-merge-related symlinks, which needs to be done manually
    if pmb.config.pmaports.read_config().get("supported_usr_merge", False):
        pmb.helpers.run.root(
            [
                "mkdir",
                "-p",
                f"{chroot.path}/usr/bin",
                f"{chroot.path}/usr/sbin",
                f"{chroot.path}/usr/lib",
            ]
        )
        pmb.helpers.run.root(["ln", "-s", "usr/bin", "usr/sbin", "usr/lib", f"{chroot.path}/"])
    # Install minimal amount of things to get a functional chroot.
    # We don't use alpine-base since it depends on openrc, and neither
    # postmarketos-base, since that's quite big (e.g: contains an init system)
    pkgs = ["alpine-baselayout", "apk-tools", "busybox", "musl-utils"]
    cmd: list[PathString] = ["--initdb"]
    pmb.helpers.apk.run([*cmd, "add", *pkgs], chroot)

    # Building chroots: create "pmos" user, add symlinks to /home/pmos
    if chroot.type != ChrootType.ROOTFS:
        pmb.chroot.root(["adduser", "-s", "/bin/sh", "-D", "pmos", "-u", pmb.config.chroot_uid_user], chroot)

        # Create the links (with subfolders if necessary)
        for src_template, link_name in pmb.config.chroot_home_symlinks.items():
            target = Path(src_template.replace("$ARCH", str(arch)))
            (chroot / link_name).parent.mkdir(exist_ok=True, parents=True)
            (chroot / target).mkdir(exist_ok=True, parents=True)
            (chroot / link_name).symlink_to(target, target_is_directory=True)
            shutil.chown(
                chroot / target, int(pmb.config.chroot_uid_user), int(pmb.config.chroot_uid_user)
            )


def shutdown(chroot: Chroot) -> None:
    """
    Shutdown a chroot, unmounting all mountpoints and removing symlinks that
    are only used at build time (e.g. /etc/apk/cache).
    """
    pmb.chroot.mount.umount_all(chroot)
    # Remove "in-pmbootstrap" marker from the chroot. This marker indicates
    # that pmbootstrap has set up all mount points etc. to run programs inside
    # the chroots, but we want it gone afterwards (e.g. when the chroot
    # contents get copied to a rootfs / installer image, or if creating an
    # android recovery zip from its contents).
    try:
        (chroot / "in-pmbootstrap").unlink()
    except FileNotFoundError:
        raise RuntimeError(f"({chroot}) attempted to shutdown chroot which wasn't initialised (/in-pmbootstrap marker missing).")

    # Remove the /cache directory
    (chroot / "cache").rmdir()
    (chroot / "etc/apk/cache").unlink()

    logging.debug("Shutdown complete")

