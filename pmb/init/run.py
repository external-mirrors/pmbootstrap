# Copyright 2025 Casey Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

# Wrappers for running commands prior to pmbootstrap init/unshare

from pmb.init.sudo import which_sudo
import subprocess
import shlex


def sudo(cmd: list[str]) -> list[str]:
    """
    Prefix with "sudo --" unless already running as root
    """
    sudo = which_sudo()
    if not sudo:
        return cmd

    return [sudo, "--", *[shlex.quote(x) for x in cmd]]


def run_root(cmd: list[str]) -> tuple[str, str]:
    """
    Run a command as root and get stdout/stderr result
    """
    proc = subprocess.run(sudo(cmd), capture_output=True)
    return (proc.stdout, proc.stderr)
