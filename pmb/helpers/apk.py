# Copyright 2023 Johannes Marbach, Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shlex
from collections.abc import Sequence
from pathlib import Path

import pmb.chroot
import pmb.config.pmaports
from pmb.core.arch import Arch
from pmb.core.chroot import Chroot
from pmb.types import PathString
import pmb.helpers.cli
import pmb.helpers.repo
import pmb.helpers.run
import pmb.helpers.run_core
import pmb.parse.version
from pmb.core.context import get_context
from pmb.helpers import logging
from pmb.meta import Cache


@Cache("root", "user_repository", mirrors_exclude=[])
def update_repository_list(
    root: Path,
    user_repository=False,
    mirrors_exclude: list[str] = [],
    check=False,
):
    """
    Update /etc/apk/repositories, if it is outdated (when the user changed the
    --mirror-alpine or --mirror-pmOS parameters).

    :param root: the root directory to operate on
    :param mirrors_exclude: mirrors to exclude from the repository list
    :param check: This function calls it self after updating the
                  /etc/apk/repositories file, to check if it was successful.
                  Only for this purpose, the "check" parameter should be set to
                  True.
    """
    # Read old entries or create folder structure
    path = root / "etc/apk/repositories"
    lines_old: list[str] = []
    if path.exists():
        # Read all old lines
        lines_old = []
        with path.open() as handle:
            for line in handle:
                lines_old.append(line[:-1])
    else:
        pmb.helpers.run.root(["mkdir", "-p", path.parent])

    # Up to date: Save cache, return
    lines_new = pmb.helpers.repo.urls(
        user_repository=user_repository, mirrors_exclude=mirrors_exclude
    )
    if lines_old == lines_new:
        return

    # Check phase: raise error when still outdated
    if check:
        raise RuntimeError(f"Failed to update: {path}")

    # Update the file
    logging.debug(f"({root.name}) update /etc/apk/repositories")
    if path.exists():
        pmb.helpers.run.root(["rm", path])
    for line in lines_new:
        pmb.helpers.run.root(["sh", "-c", "echo " f"{shlex.quote(line)} >> {path}"])
    update_repository_list(
        root, user_repository=user_repository, mirrors_exclude=mirrors_exclude, check=True
    )


def _prepare_fifo() -> Path:
    """Prepare the progress fifo for reading / writing.

    :param chroot: whether to run the command inside the chroot or on the host
    :param suffix: chroot suffix. Only applies if the "chroot" parameter is
                   set to True.
    :returns: A tuple consisting of the path to the fifo as needed by apk to
              write into it (relative to the chroot, if applicable) and the
              path of the fifo as needed by cat to read from it (always
              relative to the host)
    """
    pmb.helpers.run.root(["mkdir", "-p", get_context().config.work / "tmp"])
    fifo = get_context().config.work / "tmp/apk_progress_fifo"
    if os.path.exists(fifo):
        pmb.helpers.run.root(["rm", "-f", fifo])

    pmb.helpers.run.root(["mkfifo", fifo])
    return fifo


def _create_command_with_progress(command, fifo):
    """Build a full apk command from a subcommand, set up to redirect progress into a fifo.

    :param command: apk subcommand in list form
    :param fifo: path of the fifo
    :returns: full command in list form
    """
    flags = ["--no-progress", "--progress-fd", "3"]
    command_full = [command[0]] + flags + command[1:]
    command_flat = pmb.helpers.run_core.flat_cmd([command_full])
    command_flat = f"exec 3>{fifo}; {command_flat}"
    return ["sh", "-c", command_flat]


def _compute_progress(line):
    """Compute the progress as a number between 0 and 1.

    :param line: line as read from the progress fifo
    :returns: progress as a number between 0 and 1
    """
    if not line:
        return 1
    cur_tot = line.rstrip().split("/")
    if len(cur_tot) != 2:
        return 0
    cur = float(cur_tot[0])
    tot = float(cur_tot[1])
    return cur / tot if tot > 0 else 0


def apk_with_progress(command: Sequence[PathString], chroot: Chroot | None = None):
    """Run an apk subcommand while printing a progress bar to STDOUT.

    :param command: apk subcommand in list form
    :raises RuntimeError: when the apk command fails
    """
    fifo = _prepare_fifo()
    _command: list[str] = [str(get_context().config.work / "apk.static")]
    if chroot:
        _command.extend(["--root", str(chroot.path), "--arch", str(chroot.arch)])
    for c in command:
        if isinstance(c, Arch):
            _command.append(str(c))
        else:
            _command.append(os.fspath(c))
    command_with_progress = _create_command_with_progress(_command, fifo)
    log_msg = " ".join(_command)
    with pmb.helpers.run.root(["cat", fifo], output="pipe") as p_cat:
        with pmb.helpers.run.root(command_with_progress, output="background") as p_apk:
            while p_apk.poll() is None:
                line = p_cat.stdout.readline().decode("utf-8")
                progress = _compute_progress(line)
                pmb.helpers.cli.progress_print(progress)
            pmb.helpers.cli.progress_flush()
            pmb.helpers.run_core.check_return_code(p_apk.returncode, log_msg)


def check_outdated(version_installed, action_msg):
    """Check if the provided alpine version is outdated.

    This depends on the alpine mirrordir (edge, v3.12, ...) related to currently checked out
    pmaports branch.

    :param version_installed: currently installed apk version, e.g. "2.12.1-r0"
    :param action_msg: string explaining what the user should do to resolve
                       this
    :raises: RuntimeError if the version is outdated
    """
    channel_cfg = pmb.config.pmaports.read_config_channel()
    mirrordir_alpine = channel_cfg["mirrordir_alpine"]
    version_min = pmb.config.apk_tools_min_version[mirrordir_alpine]

    if pmb.parse.version.compare(version_installed, version_min) >= 0:
        return

    raise RuntimeError(
        "Found an outdated version of the 'apk' package"
        f" manager ({version_installed}, expected at least:"
        f" {version_min}). {action_msg}"
    )
