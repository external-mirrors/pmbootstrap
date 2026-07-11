# Copyright 2026 Stefan Hansson, Martijn Braam
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shlex
from pathlib import Path
from typing import NamedTuple

import pmb.build
import pmb.config.pmaports
import pmb.helpers.run
import pmb.helpers.run_core
import pmb.parse.apkindex
from pmb.core.arch import Arch
from pmb.core.context import get_context
from pmb.helpers import logging
from pmb.helpers.file import is_apk
from pmb.types import PathString, RunOutputTypeDefault

su_cmd = "_su=$(command -v sudo >/dev/null && echo sudo || (command -v doas >/dev/null && echo doas || echo run0)); $_su"
ssh_opts = [
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPath='~/.ssh/controlmaster_%r@%h:%p'",
    "-o",
    "ControlPersist=60",
]


class SshRemote(NamedTuple):
    user: str
    host: str
    port: str


def ssh_make_cmd(remote: SshRemote, cmd: str) -> list[PathString]:
    return [
        "ssh",
        *ssh_opts,
        "-t",
        "-p",
        remote.port,
        f"{remote.user}@{remote.host}",
        f"sh -c {shlex.quote(cmd)}",
    ]


def scp_abuild_key(remote: SshRemote) -> None:
    """
    Copy the building key of the local installation to the target device,
    so it trusts the apks that were signed here.

    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port
    """
    keys = list((get_context().config.work / "config_abuild").glob("*.pub"))
    key = keys[0]
    key_name = os.path.basename(key)

    logging.info(f"Copying signing key ({key_name}) to {remote.user}@{remote.host}")
    command: list[PathString] = [
        "scp",
        *ssh_opts,
        "-P",
        remote.port,
        key,
        f"{remote.user}@{remote.host}:/tmp",
    ]
    pmb.helpers.run.user(command, output=RunOutputTypeDefault.INTERACTIVE)

    logging.info(f"Installing signing key at {remote.user}@{remote.host}")
    keyname = os.path.join("/tmp", os.path.basename(key))
    remote_cmd_l: list[PathString] = [
        "mv",
        "-n",
        keyname,
        "/etc/apk/keys/",
    ]
    remote_cmd = pmb.helpers.run_core.flat_cmd([remote_cmd_l])
    command = ssh_make_cmd(remote, f"{su_cmd} {remote_cmd}")
    pmb.helpers.run.user(command, output=RunOutputTypeDefault.TUI)


def ssh_find_arch(remote: SshRemote) -> Arch:
    """Connect to a device via ssh and query the architecture."""
    logging.info(f"Querying architecture of {remote.user}@{remote.host}")
    # Run command in a subshell in case the foreign device has a weird uname
    # implementation, e.g. Nushell.
    command = ssh_make_cmd(remote, "uname -m")
    output = pmb.helpers.run.user_output(command)
    # Split by newlines so we can pick out any irrelevant output, e.g. the "permanently
    # added to list of known hosts" warnings.
    output_lines = output.strip().splitlines()
    # Pick out last line which should contain the foreign device's architecture
    foreign_machine_type = output_lines[-1]
    return Arch.from_machine_type(foreign_machine_type)


def ssh_list_packages(remote: SshRemote) -> set[str]:
    logging.info(f"Querying installed packages of {remote.user}@{remote.host}")
    command = ssh_make_cmd(remote, "apk list -I | cut -d' ' -f1")
    pkgs = pmb.helpers.run.user_output(command, output=RunOutputTypeDefault.NULL).split("\n")
    return {"-".join(p.split("-")[:-2]) for p in pkgs}


def ssh_install_apks(
    remote: SshRemote,
    paths: list[Path],
    install_offline: bool,
) -> None:
    """
    Copy binary packages via SCP and install them via SSH.

    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port
    :param paths: list of absolute paths to locally stored apks
    """
    remote_paths = [os.path.join("/tmp", os.path.basename(path)) for path in paths]

    logging.info(f"Copying packages to {remote.user}@{remote.host}")
    command: list[PathString] = [
        "scp",
        *ssh_opts,
        "-P",
        remote.port,
        *paths,
        f"{remote.user}@{remote.host}:/tmp",
    ]
    pmb.helpers.run.user(command, output=RunOutputTypeDefault.INTERACTIVE)

    logging.info(f"Installing packages at {remote.user}@{remote.host}")
    add_cmd_list = ["apk", "--wait", "30", "--timeout", "5"]
    if install_offline:
        add_cmd_list.append("--no-network")
    add_cmd_list.extend(["add", *remote_paths])
    add_cmd = pmb.helpers.run_core.flat_cmd([add_cmd_list])
    clean_cmd = pmb.helpers.run_core.flat_cmd([["rm", *remote_paths]])
    command = ssh_make_cmd(remote, f"{su_cmd} {add_cmd} rc=$?; {clean_cmd} exit $rc")
    pmb.helpers.run.user(command, output=RunOutputTypeDefault.TUI)


def sideload(
    user: str,
    host: str,
    port: str,
    arch: Arch | None,
    copy_key: bool,
    strict: bool,
    pkgnames: list[str],
) -> None:
    """
    Build packages if necessary and install them via SSH.

    By default sideload will use the list of packages already installed on the device
    to determine if subpackages should also be installed, this is useful to ensure
    that service files and other relevant subpackages also get updated (and don't get
    removed due to version mismatches). This behaviour can be disabled with --strict.

    Network connectivity is checked using 'nm-online' to avoid waiting for apk to timeout.

    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port
    :param arch: target device architecture
    :param copy_key: copy the abuild key too
    :param strict: don't automatically include relevant subpackages or check network connectivity
    :param pkgnames: list of pkgnames to be built
    """
    paths = []

    remote = SshRemote(user, host, port)

    if arch is None:
        arch = ssh_find_arch(remote)

    # Get currently installed packages unless running with --strict
    installed_pkgs = ssh_list_packages(remote) if not strict else []

    context = get_context()
    to_build = []
    install_offline = True
    seen = set()

    # Determine the paths to all the package apk files and select
    # additional relevant subpackages to also upgrade
    while pkgnames:
        pkgname = pkgnames.pop(0)

        data_repo = pmb.parse.apkindex.package(pkgname, arch, False)

        if data_repo is None:
            package_path = Path(pkgname)

            if is_apk(package_path):
                paths.append(package_path)
                continue
            else:
                raise RuntimeError(f"Couldn't find APKINDEX data for {pkgname}!")

        base_aports, apkbuild = pmb.build.get_apkbuild(pkgname)

        # Also sideload other subpackages if they're already installed (e.g. *-systemd packages)
        if not strict and apkbuild is not None and apkbuild["pkgname"] not in seen:
            additional = {subpkg for subpkg in apkbuild["subpackages"] if subpkg in installed_pkgs}
            if additional:
                logging.info(
                    f"{apkbuild['pkgname']}: including subpackages: {', '.join(additional)}"
                )
                pkgnames.extend(a for a in additional if a not in seen)
                seen.update(additional)

        channel = pmb.config.pmaports.read_config(base_aports)["channel"]

        apk_file = f"{pkgname}-{data_repo.version}.apk"
        host_path = context.config.work / "packages" / channel / arch / apk_file

        # We try to run apk with --no-network to avoid waiting for APKINDEX
        # updates, but if the package has dependencies that aren't already
        # installed then we can't do this.
        if data_repo.depends and not all(dep in installed_pkgs for dep in data_repo.depends):
            install_offline = False

        if not host_path.is_file():
            to_build.append(pkgname)

        seen.add(pkgname)
        paths.append(host_path)

    if to_build:
        pmb.build.packages(context, to_build, arch, force=True)
        # Check all the packages actually got builts
        for path in paths:
            if not path.is_file():
                raise RuntimeError(f"The package '{path.name}' could not be built")

    if copy_key:
        scp_abuild_key(remote)

    ssh_install_apks(remote, paths, install_offline)
