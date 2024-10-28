# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import shutil
import subprocess
from pmb.core.arch import Arch
from pmb.core.chroot import Chroot
from pmb.core.context import get_context
from pmb.core.pkgrepo import pkgrepo_default_path
import pmb.helpers.run_core
from collections.abc import Sequence
from pmb.types import Env, PathString


def user(
    cmd: Sequence[PathString],
    working_dir: Path | None = None,
    output: str = "log",
    output_return: bool = False,
    check: bool | None = None,
    env: Env = {},
    sudo: bool = False,
) -> str | int | subprocess.Popen:
    """
    Run a command on the host system as user.

    :param env: dict of environment variables to be passed to the command, e.g.
                {"JOBS": "5"}

    See pmb.helpers.run_core.core() for a detailed description of all other
    arguments and the return value.
    """
    cmd_parts = []
    for c in cmd:
        if isinstance(c, Arch):
            c = str(c)
        else:
            c = os.fspath(c)
        cmd_parts.append(c)
    # Readable log message (without all the escaping)
    msg = "% "
    for key, value in env.items():
        msg += f"{key}={value} "
    if working_dir is not None:
        msg += f"cd {os.fspath(working_dir)}; "
    msg += " ".join(cmd_parts)

    # Add environment variables and run
    env = env.copy()
    pmb.helpers.run_core.add_proxy_env_vars(env)
    if env:
        cmd_parts = ["sh", "-c", pmb.helpers.run_core.flat_cmd([cmd_parts], env=env)]
    return pmb.helpers.run_core.core(
        msg, cmd_parts, working_dir, output, output_return, check, sudo
    )


# FIXME: should probably use some kind of wrapper class / builder pattern for all these parameters...
def user_output(
    cmd: Sequence[PathString],
    working_dir: Path | None = None,
    output: str = "log",
    check: bool | None = None,
    env: Env = {},
    sudo: bool = False,
) -> str:
    ret = user(cmd, working_dir, output, output_return=True, check=check, env=env, sudo=sudo)
    if not isinstance(ret, str):
        raise TypeError("Expected str output, got " + str(ret))

    return ret


def sandbox_executable() -> list[str]:
    python = shutil.which("python", path=pmb.config.chroot_host_path)
    assert python is not None, "python not found in $PATH?"
    return [python, os.fspath(pmb.config.pmb_src / "pmb/sandbox.py")]


def get_mountpoints(chroot: Chroot, dynamic=True) -> dict[str, tuple[str, str]]:
    arch = chroot.arch
    channel = pmb.config.pmaports.read_config(pkgrepo_default_path())["channel"]
    mountpoints: dict[str, tuple[str, str]] = {}
    for src_template, target_template in pmb.config.chroot_mount_bind.items():
        src_template = src_template.replace("$WORK", os.fspath(get_context().config.work))
        src_template = src_template.replace("$ARCH", str(arch))
        src_template = src_template.replace("$CHANNEL", channel)
        target: str = target_template.strip("/")
        if not (chroot / target).exists():
            (chroot / target).mkdir(parents=True)
        mountpoints[src_template] = ("--bind", target_template)

    if not dynamic:
        return mountpoints

    for src, target in chroot.bindmounts.items():
        mountpoints[src] = ("--bind", target)

    for src, target in chroot.symlinks.items():
        mountpoints[src] = ("--symlink", target)

    return mountpoints


def sandbox(
    cmd: Sequence[PathString],
    chroot: Chroot | None = None,
    working_dir: Path | None = None,
    output="tui",
    _custom_args: list[str] = ["--become-root", "--suppress-chown"],
):
    _cmd = sandbox_executable()
    work = get_context().config.work

    _cmd.extend(
        [
            # FIXME: we still have to support split /usr for running
            # on pmOS/Alpine hosts
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/sbin",
            "/sbin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--ro-bind-try",
            "/etc/resolv.conf",
            "/etc/resolv.conf",
            # Set up a r/w overlayfs on /usr/bin
            # "--overlay-lowerdir",
            # "/usr/bin",
            # "--overlay-upperdir",
            # "tmpfs",
            # "--overlay",
            # "/usr/bin",
            # Mount the pmb workdir to /work
            "--bind",
            os.fspath(work),
            "/work",
            # "--symlink",
            # "/work/apk.static",
            # "/usr/bin/apk",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            *_custom_args,
            # "--become-root",
            # "--suppress-chown",
        ]
    )

    if chroot is not None:
        target_root = f"/work/{chroot.dirname}"
        mountpoints = get_mountpoints(chroot, dynamic=False)
        for source, (arg, target) in mountpoints.items():
            _cmd.extend(
                [
                    arg,
                    source,
                    f"{target_root}{target}",
                ]
            )
        _cmd.extend(["--dev", f"{target_root}/dev", "--proc", f"{target_root}/proc"])

    if working_dir:
        _cmd.extend(["--chdir", str(working_dir)])

    cmd_parts = []
    _work = os.fspath(work)
    for c in cmd:
        if isinstance(c, Arch):
            c = str(c)
        else:
            c = os.fspath(c)
        # Since we're binding the workdir to /work, update
        # any paths in the command
        c = c.replace(_work, "/work")
        cmd_parts.append(c)

    _cmd.extend(["sh", "-c", pmb.helpers.run_core.flat_cmd([cmd_parts])])

    pmb.helpers.run_core.core(" ".join(_cmd), _cmd, check=True, output=output)


def root(
    cmd: Sequence[PathString],
    working_dir=None,
    output="log",
    output_return=False,
    check=None,
    env={},
):
    """Run a command on the host system as root, with sudo or doas.

    :param env: dict of environment variables to be passed to the command, e.g.
                {"JOBS": "5"}

    See pmb.helpers.run_core.core() for a detailed description of all other
    arguments and the return value.
    """
    env = env.copy()
    pmb.helpers.run_core.add_proxy_env_vars(env)

    cmd = [str(x) for x in cmd]

    # if "/home/cas/.local/var/pmbootstrap/chroot_native/etc/apk" in cmd:
    #     traceback.print_stack()

    if env:
        cmd = ["sh", "-c", pmb.helpers.run_core.flat_cmd([cmd], env=env)]
    cmd = pmb.config.sudo(cmd)

    return user(cmd, working_dir, output, output_return, check, env, True)
