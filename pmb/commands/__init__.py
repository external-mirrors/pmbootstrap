# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import enum
from typing import Optional
from collections.abc import Generator
from pathlib import Path, PosixPath, PurePosixPath
from pmb.types import PmbArgs
from pmb.helpers import frontend

from .aportgen import aportgen
from .flasher import flasher
from .log import log
from .index import index
from .repo_bootstrap import RepoBootstrap
from .shutdown import shutdown
from .test import test
from .pkgrel_bump import pkgrel_bump
from .pkgver_bump import pkgver_bump
from .pull import pull
from .kconfig import KConfigCheck, KConfigEdit, KConfigMigrate

"""New way to model pmbootstrap subcommands that can be invoked without PmbArgs."""

# Commands that are still invoked via pmb/helpers/frontend.py
unmigrated_commands = [
    "init",
    "work_migrate",
    "repo_missing",
    "export",
    "sideload",
    "netboot",
    "initfs",
    "qemu",
    "aportupgrade",
    "newapkbuild",
    "lint",
    "status",
    "ci",
    "zap",
    "stats",
    "update",
    "build_init",
    "chroot",
    "install",
    "checksum",
    "build",
    "apkbuild_parse",
    "apkindex_parse",
    "config",
    "bootimg_analyze",
]


def run_command(args: PmbArgs) -> None:
    # Handle deprecated command format
    if args.action in unmigrated_commands:
        getattr(frontend, args.action)(args)
        return

    match args.action:
        case "aportgen":
            aportgen(args.packages, args.fork_alpine, args.fork_alpine_retain_branch)
        case "flasher":
            flasher(
                args.action_flasher,
                # FIXME: defaults copied from pmb/helpers/arguments.py
                # we should have these defaults defined in one place!
                getattr(args, "autoinstall", True),
                getattr(args, "cmdline", None),
                args.flash_method,
                getattr(args, "no_reboot", None),
                getattr(args, "partition", None),
                getattr(args, "resume", None),
            )
        case "log":
            log(args.clear_log, args.lines)
        case "index":
            # FIXME: should index support --arch?
            index()
        case "repo_bootstrap":
            RepoBootstrap(args.arch, args.repository).run()
        case "shutdown":
            shutdown()
        case "test":
            test(args.action_test)
        case "pkgrel_bump":
            pkgrel_bump(args.packages, args.dry, args.auto)
        case "pkgver_bump":
            pkgver_bump(args.packages)
        case "pull":
            pull()
        case "kconfig":
            match args.action_kconfig:
                case "check":
                    KConfigCheck(
                        args.kconfig_check_details, args.file, args.package, args.keep_going
                    ).run()
                case "edit":
                    KConfigEdit(args.package[0], args.arch, args.xconfig, args.nconfig).run()
                case "migrate":
                    KConfigMigrate(args.package, args.arch).run()
        case _:
            raise NotImplementedError(f"Command '{args.action}' is not implemented.")
