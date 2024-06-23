# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from pmb import commands
from pmb.core.context import get_context
from pmb.helpers.other import folder_size
import pmb.config
import pmb.chroot


def human_readable(size: float) -> str:
    styles = pmb.config.styles
    unit = ""
    col = styles['GREEN']
    for unit in ["B", "KiB", "MiB"]:
        if size < 1024:
            break
        size /= 1024
    else:
        unit = "GiB"
        col = styles['RED'] if size > 8 else styles['YELLOW'] if size > 4 else styles['GREEN']

    return f"{col}{size:.2f} {unit}"


class Du(commands.Command):
    def __init__(self):
        pass

    def run(self):
        pmb.chroot.shutdown()
        styles = pmb.config.styles
        work = get_context().config.work
        print(f"{styles['BLUE']}{work}{styles['END']}:")
        total = 0
        for item in work.iterdir():
            if not item.is_dir():
                continue
            # Skip stuff we don't want to see
            if item.name in ["cache_git", "aportgen", "tmp"]:
                continue
            size = folder_size(item)
            total += size
            print(f"{item.name:<22}: {human_readable(size)}{styles['END']}")
        print(f"\n{'Total':<22}: {human_readable(total)}{styles['END']}")
