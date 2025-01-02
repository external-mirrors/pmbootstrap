# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

import enum
from pathlib import Path
from pmb.core.pkgrepo import pkgrepo_name, pkgrepo_paths
import pmb.helpers.run
import pmb.chroot

from pmb.core import Context
from pmb.core.arch import Arch
from pmb.core.chroot import Chroot
from pmb.helpers import logging
from pmb.types import Apkbuild, CrossCompileType, Env


class BootstrapStage(enum.IntEnum):
    """
    Pass a BOOTSTRAP= environment variable with the given value to abuild. See
    bootstrap_1 etc. at https://postmarketos.org/pmaports.cfg for details.
    """

    NONE = 0
    # We don't need explicit representations of the other numbers.


def override_source(
    apkbuild: Apkbuild, pkgver: str, src: str | None, chroot: Chroot = Chroot.native()
) -> None:
    """Mount local source inside chroot and append new functions (prepare() etc.)
    to the APKBUILD to make it use the local source.
    """
    if not src:
        return

    # Mount source in chroot
    mount_path = "/mnt/pmbootstrap/source-override/"
    mount_path_outside = chroot / mount_path
    pmb.helpers.mount.bind(src, mount_path_outside, umount=True)

    # Delete existing append file
    append_path = "/tmp/APKBUILD.append"
    append_path_outside = chroot / append_path
    if append_path_outside.exists():
        pmb.chroot.root(["rm", append_path], chroot)

    # Add src path to pkgdesc, cut it off after max length
    pkgdesc = ("[" + src + "] " + apkbuild["pkgdesc"])[:127]

    pkgname = apkbuild["pkgname"]

    # Appended content
    append = (
        """
             # ** Overrides below appended by pmbootstrap for --src **

             pkgver=\""""
        + pkgver
        + """\"
             pkgdesc=\""""
        + pkgdesc
        + """\"
             _pmb_src_copy="/tmp/pmbootstrap-local-source-copy"

             # Empty $source avoids patching in prepare()
             _pmb_source_original="$source"
             source=""
             sha512sums=""

             fetch() {
                 # Update source copy
                 msg "Copying source from host system: """
        + src
        + """\"
                 local exclude_from=\""""
        + mount_path
        + """/.gitignore\"
                 local rsync_args=""
                 if [ -f "$exclude_from" ]; then
                     rsync_args="--exclude-from=\"$exclude_from\""
                 fi
                 if ! [ \""""
        + pkgname
        + """\" = "$(cat /tmp/src-pkgname)" ]; then
                     rsync_args="--delete $rsync_args"
                 fi
                 rsync -a --exclude=".git/" $rsync_args --ignore-errors --force \\
                     \""""
        + mount_path
        + """\" "$_pmb_src_copy" || true

                 # Link local source files (e.g. kernel config)
                 mkdir "$srcdir"
                 local s
                 for s in $_pmb_source_original; do
                     is_remote "$s" || ln -sf "$startdir/$s" "$srcdir/"
                 done
                 
                 echo \""""
        + pkgname
        + """\" > /tmp/src-pkgname
             }

             unpack() {
                 ln -sv "$_pmb_src_copy" "$builddir"
             }
             """
    )

    # Write and log append file
    with open(append_path_outside, "w", encoding="utf-8") as handle:
        for line in append.split("\n"):
            handle.write(line[13:].replace(" " * 4, "\t") + "\n")
    pmb.chroot.user(["cat", append_path], chroot)

    # Append it to the APKBUILD
    apkbuild_path = "/home/pmos/build/APKBUILD"
    shell_cmd = "cat " + apkbuild_path + " " + append_path + " > " + append_path + "_"
    pmb.chroot.user(["sh", "-c", shell_cmd], chroot)
    pmb.chroot.user(["mv", append_path + "_", apkbuild_path], chroot)


def mount_pmaports(chroot: Chroot = Chroot.native()) -> dict[str, Path]:
    """
    Mount pmaports.git in chroot.

    :param chroot: chroot to target
    :returns: dictionary mapping pkgrepo name to dest path
    """
    dest_paths = {}
    for repo in pkgrepo_paths(skip_extras=True):
        destination = Path("/mnt") / pkgrepo_name(repo)
        outside_destination = chroot / destination
        pmb.helpers.mount.bind(repo, outside_destination, umount=True)
        dest_paths[pkgrepo_name(repo)] = destination

    return dest_paths


def link_to_git_dir(chroot: Chroot) -> None:
    """Make ``/home/pmos/build/.git`` point to the .git dir from pmaports.git, with a
    symlink so abuild does not fail (#1841).

    abuild expects the current working directory to be a subdirectory of a
    cloned git repository (e.g. main/openrc from aports.git). If git is
    installed, it will try to get the last git commit from that repository, and
    place it in the resulting apk (.PKGINFO) as well as use the date from that
    commit as SOURCE_DATE_EPOCH (for reproducible builds).

    With that symlink, we actually make it use the last git commit from
    pmaports.git for SOURCE_DATE_EPOCH and have that in the resulting apk's
    .PKGINFO.
    """
    # Mount pmaports.git in chroot, in case the user did not use pmbootstrap to
    # clone it (e.g. how we build on sourcehut). Do this here and not at the
    # initialization of the chroot, because the pmaports dir may not exist yet
    # at that point. Use umount=True, so we don't have an old path mounted
    # (some tests change the pmaports dir).
    dest_paths = mount_pmaports(chroot)

    # Create .git symlink
    pmb.chroot.user(["mkdir", "-p", "/home/pmos/build"], chroot)
    pmb.chroot.user(["ln", "-sf", dest_paths["pmaports"] / ".git", "/home/pmos/build/.git"], chroot)


def handle_csum_failure(apkbuild: Apkbuild, chroot: Chroot) -> None:
    csum_fail_path = chroot / "tmp/apkbuild_verify_failed"
    if not csum_fail_path.exists():
        return

    reason = csum_fail_path.open().read().strip()
    if reason == "local":
        logging.info(
            "WARNING: Some checksums didn't match, run"
            f" 'pmbootstrap checksum {apkbuild['pkgname']}' to fix them."
        )
    else:
        logging.error(f"ERROR: Remote checksum mismatch for {apkbuild['pkgname']}")
        logging.error("NOTE: If you just modified this package:")
        logging.error(
            f" * run 'pmbootstrap checksum {apkbuild['pkgname']}' to update the checksums."
        )
        logging.error("If you didn't modify it, try building again to re-download the sources.")
        raise RuntimeError(f"Remote checksum mismatch for {apkbuild['pkgname']}")


def run_abuild(
    context: Context,
    apkbuild: Apkbuild,
    pkgver: str,
    channel: str,
    arch: Arch,
    strict: bool = False,
    force: bool = False,
    cross: CrossCompileType = None,
    suffix: Chroot = Chroot.native(),
    src: str | None = None,
    bootstrap_stage: int = BootstrapStage.NONE,
) -> None:
    """
    Set up all environment variables and construct the abuild command (all
    depending on the cross-compiler method and target architecture), copy
    the aport to the chroot and execute abuild.

    :param cross: None, "native", or "crossdirect"
    :param src: override source used to build the package with a local folder
    :param bootstrap_stage: pass a BOOTSTRAP= env var with the value to abuild
    :returns: (output, cmd, env), output is the destination apk path relative
              to the package folder ("x86_64/hello-1-r2.apk"). cmd and env are
              used by the test case, and they are the full abuild command and
              the environment variables dict generated in this function.
    """
    # Sanity check
    if cross == "native" and "!tracedeps" not in apkbuild["options"]:
        logging.info(
            "WARNING: Option !tracedeps is not set, but we're"
            " cross-compiling in the native chroot. This will"
            " probably fail!"
        )
    pkgdir = context.config.work / "packages" / channel
    if not pkgdir.exists():
        pmb.helpers.run.root(["mkdir", "-p", pkgdir])
        pmb.helpers.run.root(
            [
                "chown",
                "-R",
                f"{pmb.config.chroot_uid_user}:{pmb.config.chroot_uid_user}",
                pkgdir.parent,
            ]
        )

    pmb.chroot.rootm(
        [
            ["mkdir", "-p", "/home/pmos/packages"],
            ["rm", "-f", "/home/pmos/packages/pmos"],
            ["ln", "-sf", f"/mnt/pmbootstrap/packages/{channel}", "/home/pmos/packages/pmos"],
        ],
        suffix,
    )

    # Environment variables
    env: Env = {"CARCH": str(arch), "SUDO_APK": "abuild-apk --no-progress"}
    if cross == "native":
        hostspec = arch.alpine_triple()
        env["CROSS_COMPILE"] = hostspec + "-"
        env["CC"] = hostspec + "-gcc"
    if cross == "crossdirect":
        env["PATH"] = ":".join([f"/native/usr/lib/crossdirect/{arch}", pmb.config.chroot_path])
    if not context.ccache:
        env["CCACHE_DISABLE"] = "1"

    # Use sccache without crossdirect (crossdirect uses it via rustc.sh)
    if context.ccache and cross != "crossdirect":
        env["RUSTC_WRAPPER"] = "/usr/bin/sccache"

    # Cache binary objects from go in this path (like ccache)
    env["GOCACHE"] = "/home/pmos/.cache/go-build"

    # Cache go modules (git repositories). Usually these should be bundled and
    # it should not be required to download them at build time, in that case
    # the APKBUILD sets the GOPATH (and therefore indirectly GOMODCACHE). But
    # e.g. when using --src they are not bundled, in that case it makes sense
    # to point GOMODCACHE at pmbootstrap's work dir so the modules are only
    # downloaded once.
    if context.go_mod_cache:
        env["GOMODCACHE"] = "/home/pmos/go/pkg/mod"

    if bootstrap_stage:
        env["BOOTSTRAP"] = str(bootstrap_stage)

    # Build the abuild command
    cmd = ["abuild", "-D", "postmarketOS"]
    if strict or "pmb:strict" in apkbuild["options"]:
        if not strict:
            logging.debug(
                apkbuild["pkgname"] + ": 'pmb:strict' found in" " options, building in strict mode"
            )
        cmd += ["-r"]  # install depends with abuild
    else:
        cmd += ["-d"]  # do not install depends with abuild
    if force:
        cmd += ["-f"]
    if src:
        # Keep build artifacts, so repeated invocations will do incremental
        # building.
        cmd += ["-K"]

    # Copy the aport to the chroot and build it
    pmb.build.copy_to_buildpath(apkbuild["pkgname"], suffix, no_override=strict)
    if src and strict:
        logging.debug(f"({suffix}) Ensuring previous build artifacts are removed")
        pmb.chroot.root(["rm", "-rf", "/tmp/pmbootstrap-local-source-copy"], suffix)
    override_source(apkbuild, pkgver, src, suffix)
    link_to_git_dir(suffix)

    try:
        pmb.chroot.user(cmd, suffix, Path("/home/pmos/build"), env=env)
    finally:
        handle_csum_failure(apkbuild, suffix)
