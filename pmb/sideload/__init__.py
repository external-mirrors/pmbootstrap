# Copyright 2023 Martijn Braam
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from typing import Optional
from pmb.core.arch import Arch
from pmb.helpers import logging
import shlex

from pmb.types import PathString, PmbArgs
import pmb.helpers.run
import pmb.helpers.run_core
import pmb.parse.apkindex
import pmb.config.pmaports
import pmb.build
from pmb.core.context import get_context


def scp_abuild_key(args: PmbArgs, user: str, host: str, port: str) -> None:
    """Copy the building key of the local installation to the target device,
    so it trusts the apks that were signed here.
    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port"""

    keys = list((get_context().config.work / "config_abuild").glob("*.pub"))
    key = keys[0]
    key_name = os.path.basename(key)

    logging.info(f"Copying signing key ({key_name}) to {user}@{host}")
    command: list[PathString] = ["scp", "-P", port, key, f"{user}@{host}:/tmp"]
    pmb.helpers.run.user(command, output="interactive")

    logging.info(f"Installing signing key at {user}@{host}")
    keyname = os.path.join("/tmp", os.path.basename(key))
    remote_cmd_l: list[PathString] = [
        "sudo",
        "-p",
        pmb.config.sideload_sudo_prompt,
        "-S",
        "mv",
        "-n",
        keyname,
        "/etc/apk/keys/",
    ]
    remote_cmd = pmb.helpers.run_core.flat_cmd([remote_cmd_l])
    command = ["ssh", "-t", "-p", port, f"{user}@{host}", remote_cmd]
    pmb.helpers.run.user(command, output="tui")


def ssh_find_arch(args: PmbArgs, user: str, host: str, port: str) -> Arch:
    """Connect to a device via ssh and query the architecture."""
    logging.info(f"Querying architecture of {user}@{host}")
    # Run command in a subshell in case the foreign device has a weird uname
    # implementation, e.g. Nushell.
    architecture_cmd = shlex.quote("uname -m")
    command = ["ssh", "-p", port, f"{user}@{host}", f"sh -c {architecture_cmd}"]
    output = pmb.helpers.run.user_output(command)
    # Split by newlines so we can pick out any irrelevant output, e.g. the "permanently
    # added to list of known hosts" warnings.
    output_lines = output.strip().splitlines()
    # Pick out last line which should contain the foreign device's architecture
    foreign_machine_type = output_lines[-1]
    alpine_architecture = Arch.from_machine_type(foreign_machine_type)
    return alpine_architecture


def ssh_install_apks(args: PmbArgs, user, host, port, paths: list) -> None:
    """Copy binary packages via SCP and install them via SSH.
    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port
    :param paths: list of absolute paths to locally stored apks
    """

    remote_paths = []
    for path in paths:
        remote_paths.append(os.path.join("/tmp", os.path.basename(path)))

    logging.info(f"Copying packages to {user}@{host}")
    command = ["scp", "-P", port] + paths + [f"{user}@{host}:/tmp"]
    pmb.helpers.run.user(command, output="interactive")

    logging.info(f"Installing packages at {user}@{host}")
    add_cmd = [
        "sudo",
        "-p",
        pmb.config.sideload_sudo_prompt,
        "-S",
        "apk",
        "--wait",
        "30",
        "add",
    ] + remote_paths
    add_cmd = pmb.helpers.run_core.flat_cmd([add_cmd])
    clean_cmd = pmb.helpers.run_core.flat_cmd([["rm"] + remote_paths])
    add_cmd_complete = shlex.quote(f"{add_cmd} rc=$?; {clean_cmd} exit $rc")
    # Run apk command in a subshell in case the foreign device has a non-POSIX shell.
    command = ["ssh", "-t", "-p", port, f"{user}@{host}", f"sh -c {add_cmd_complete}"]
    pmb.helpers.run.user(command, output="tui")


def sideload(
    args: PmbArgs, user: str, host: str, port: str, arch: Arch | None, copy_key: bool, pkgnames
) -> None:
    """Build packages if necessary and install them via SSH.

    :param user: target device ssh username
    :param host: target device ssh hostname
    :param port: target device ssh port
    :param arch: target device architecture
    :param copy_key: copy the abuild key too
    :param pkgnames: list of pkgnames to be built"""

    paths = []
    channel: str = pmb.config.pmaports.read_config()["channel"]

    if arch is None:
        arch = ssh_find_arch(args, user, host, port)

    context = get_context()
    to_build = []
    for pkgname in pkgnames:
        data_repo = pmb.parse.apkindex.package(pkgname, arch, True)
        apk_file = f"{pkgname}-{data_repo['version']}.apk"
        host_path = context.config.work / "packages" / channel / arch / apk_file
        if not host_path.is_file():
            to_build.append(pkgname)

        paths.append(host_path)

    if to_build:
        pmb.build.packages(context, to_build, arch, force=True)
        # Check all the packages actually got builts
        for path in paths:
            if not path.is_file():
                raise RuntimeError(f"The package '{pkgname}' could not be built")

    if copy_key:
        scp_abuild_key(args, user, host, port)

    ssh_install_apks(args, user, host, port, paths)
