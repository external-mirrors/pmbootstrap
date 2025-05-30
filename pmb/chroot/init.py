# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import enum
from pathlib import Path
from pmb.meta import Cache
from pmb.helpers import logging
import os
import shutil

import pmb.chroot
import pmb.config
import pmb.config.workdir
import pmb.helpers.apk_static
import pmb.helpers.apk
import pmb.helpers.repo
import pmb.helpers.run
from pmb.core import Chroot, ChrootType
from pmb.core.context import get_context
from pmb.types import PathString


class UsrMerge(enum.Enum):
    """
    Merge /usr while initializing chroot.
    https://systemd.io/THE_CASE_FOR_THE_USR_MERGE/
    """

    AUTO = 0
    ON = 1
    OFF = 2


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


def init_usr_merge(chroot: Chroot) -> None:
    logging.info(f"({chroot}) merge /usr")
    script = f"{pmb.config.pmb_src}/pmb/data/merge-usr.sh"
    pmb.helpers.run.root(["sh", "-e", script, "CALLED_FROM_PMB", chroot.path])


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
        cache_target.symlink_to(f"/cache/apk_{chroot.arch}")


@Cache("chroot")
def init(chroot: Chroot, usr_merge: UsrMerge = UsrMerge.AUTO) -> None:
    """
    Initialize a chroot by copying the resolv.conf and updating
    /etc/apk/repositories. If /bin/sh is missing, create the chroot from
    scratch.

    :param usr_merge: set to ON to force having a merged /usr. With AUTO it is
                      only done if the user chose to install systemd in
                      pmbootstrap init.
    """
    # When already initialized: just prepare the chroot
    arch = chroot.arch

    # We plan to ship systemd with split /usr until the /usr merge is complete
    # in Alpine. Let's not drop all our code yet but just forcefully disable
    # it.
    usr_merge = UsrMerge.OFF

    config = get_context().config

    # If the channel is wrong and the user has auto_zap_misconfigured_chroots
    # enabled, zap the chroot and reinitialize it
    if chroot.exists():
        zap = pmb.config.workdir.chroot_check_channel(chroot)
        if zap:
            pmb.chroot.del_chroot(chroot.path, confirm=False)
            pmb.config.workdir.clean()

    pmb.chroot.mount(chroot)
    mark_in_chroot(chroot)
    if chroot.exists():
        pmb.helpers.apk.update_repository_list(chroot.path)
        copy_resolv_conf(chroot)
        warn_if_chroots_outdated()
        setup_cache_path(chroot)
        return

    # Fetch apk.static
    pmb.helpers.apk_static.init()

    logging.info(f"({chroot}) Creating chroot")

    # Initialize /etc/apk/keys/, resolv.conf, repositories
    init_keys(chroot)
    # Also creates /etc
    pmb.helpers.apk.update_repository_list(chroot.path)
    copy_resolv_conf(chroot)
    setup_cache_path(chroot)

    pmb.config.workdir.chroot_save_init(chroot)

    # Install minimal amount of things to get a functional chroot.
    # We don't use alpine-base since it depends on openrc, and neither
    # postmarketos-base, since that's quite big (e.g: contains an init system)
    pmb.helpers.repo.update(arch)
    pkgs = ["alpine-baselayout", "apk-tools", "busybox", "musl-utils"]
    cmd: list[PathString] = ["--initdb"]
    pmb.helpers.apk.run([*cmd, "add", *pkgs], chroot)

    # Merge /usr
    if usr_merge is UsrMerge.AUTO and pmb.config.is_systemd_selected(config):
        usr_merge = UsrMerge.ON
    if usr_merge is UsrMerge.ON:
        init_usr_merge(chroot)

    # Building chroots: create "pmos" user, add symlinks to /home/pmos
    if not chroot.type == ChrootType.ROOTFS:
        pmb.chroot.root(
            ["adduser", "-s", "/bin/sh", "-D", "pmos", "-u", pmb.config.chroot_uid_user], chroot
        )

        # Create the links (with subfolders if necessary)
        for src_template, link_name in pmb.config.chroot_home_symlinks.items():
            target = Path(src_template.replace("$ARCH", str(arch)))
            (chroot / link_name).parent.mkdir(exist_ok=True, parents=True)
            (chroot / target).mkdir(exist_ok=True, parents=True)
            (chroot / link_name).symlink_to(target, target_is_directory=True)
            shutil.chown(
                chroot / target, int(pmb.config.chroot_uid_user), int(pmb.config.chroot_uid_user)
            )


def shutdown() -> None:
    # Remove "in-pmbootstrap" marker from all chroots. This marker indicates
    # that pmbootstrap has set up all mount points etc. to run programs inside
    # the chroots, but we want it gone afterwards (e.g. when the chroot
    # contents get copied to a rootfs / installer image, or if creating an
    # android recovery zip from its contents).
    for marker in get_context().config.work.glob("chroot_*/in-pmbootstrap"):
        pmb.helpers.run.root(["rm", marker])

    logging.debug("Shutdown complete")

