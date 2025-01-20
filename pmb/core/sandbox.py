# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from pmb.types import PathString, Arch
from .chroot import Chroot
from abc import abstractmethod
import pmb.config
import os
import shutil
import pmb.helpers.repo
import pmb.helpers.run_core
from typing import Self, override
from pathlib import Path
from .context import get_context
from pmb.helpers import xhash


class FSOp:
    def __init__(self, dest: str) -> None:
        self.dest = dest

    @abstractmethod
    def args(self) -> list[str]: ...


class BindOp(FSOp):
    def __init__(
        self, src: str, dest: str, *, readonly: bool = False, required: bool = True
    ) -> None:
        self.src = src
        self.readonly = readonly
        self.required = required
        super().__init__(dest)

    def args(self) -> list[str]:
        return [
            "--"
            + ("ro-" if self.readonly else "")
            + "bind"
            + ("-try" if not self.required else ""),
            self.src,
            self.dest,
        ]


class ProcOp(FSOp):
    def args(self) -> list[str]:
        return ["--proc", self.dest]


class DevOp(FSOp):
    def args(self) -> list[str]:
        return ["--dev", self.dest]


class TmpOp(FSOp):
    def args(self) -> list[str]:
        return ["--tmpfs", self.dest]

class OverlayOp(FSOp):
    def __init__(self, lowerdirs: tuple[str, ...], upperdir: str, workdir: str, dst: str) -> None:
        self.lowerdirs = lowerdirs
        self.upperdir = upperdir
        self.workdir = workdir
        super().__init__(dst)


class EnvOp(FSOp):
    def __init__(self, var: str, val: str):
        self.var = var
        self.val = val

    def args(self) -> list[str]:
        return ["--setenv", self.var, self.val]


def sandbox_executable() -> list[str]:
    python = shutil.which("python", path=pmb.config.host_path)
    assert python is not None, "python not found in $PATH?"
    return [python, os.fspath(pmb.config.pmb_src / "pmb/sandbox.py")]


class Sandbox:
    def __init__(self, sbox_cmd: list[str]):
        self.sbox_cmd = sbox_cmd

    def run(self, cmd: list[str], interactive: bool = False) -> str:
        cmd = [*self.sbox_cmd, *cmd]
        print(cmd)
        # print(f"$ {' '.join(cmd)}")
        code, output = pmb.helpers.run_core.foreground_pipe(
            cmd,
            output_log = interactive,
            output_return = True,
        )
        pmb.helpers.run_core.check_return_code(code, f"$ {' '.join(cmd)}")
        return output


class SandboxBase:
    __fsops: list[FSOp]
    name: str
    __become: int
    __chdir: str | None

    def __init__(
        self, name: str, fsops: list[FSOp], *, uid: int = -1, chdir: PathString | None = None
    ) -> None:
        """
        Initialize a sandbox for :chdir: with identifier :name:
        """

        self.__become = uid
        self.__chdir = str(chdir) if chdir else None
        self.name = name
        self.__fsops = [
            *fsops,
            BindOp("/etc/resolv.conf", "/etc/resolv.conf", readonly=True, required=False),
            DevOp("/dev"),
            ProcOp("/proc"),
        ]

    def with_chdir(self, chdir: PathString | None) -> Self:
        self.__chdir = chdir
        return self

    def bind(self, src: PathString, dest: PathString, *, readonly: bool = False, required: bool = True) -> Self:
        self.__fsops.append(BindOp(str(src), str(dest), readonly=readonly, required=required))
        return self

    def args(self) -> list[str]:
        fsops = self.__fsops
        if self.__chdir is not None:
            fsops.append(BindOp(self.__chdir, self.__chdir))

        args = [arg for op in fsops for arg in op.args()]
        if self.__become >= 0:
            args = [*args, "--become", f"{self.__become}:{self.__become}"]

        if self.__chdir is not None:
            args = [*args, "--chdir", self.__chdir]

        return [*args, "--suppress-chown"]

    def with_uid(self, uid: int) -> Self:
        """
        Enter the sandbox as a specific UID
        """
        self.__become = uid

    def build(self) -> Sandbox:
        return Sandbox([*sandbox_executable(), *self.args()])


class HostSandbox(SandboxBase):
    """
    Sandbox running in the host context
    """

    def __init__(self, chdir: PathString | None = None) -> None:
        super().__init__(
            "host",
            [
                BindOp("/usr", "/usr", readonly=True),
                BindOp("/bin", "/bin", readonly=True),
                BindOp("/sbin", "/sbin", readonly=True),
                BindOp("/lib", "/lib", readonly=True),
                BindOp("/lib64", "/lib64", readonly=True, required=False),
                BindOp(str(get_context().config.work), "/work"),
            ],
            uid=0,
            chdir=chdir,
        )


def run_sandboxed(cmd: list[PathString], *, chdir: PathString | None = None) -> None:
    host_sbox = HostSandbox()

    host_sbox.with_chdir(chdir)
    host_sbox.run(cmd)


class ApkTools:
    """
    Wrapper around apk.static
    """

    sandbox: Sandbox

    def __init__(self, root: Path, arch: Arch):
        self.root_outer = root
        self.root = f"/work/{root.relative_to(get_context().config.work)}"
        self.arch = arch

    def __enter__(self) -> Self:
        self.sandbox = (
            HostSandbox()
            .bind(f"{get_context().config.work}/config_apk_keys", f"{self.root}/etc/apk/keys")
            .build()
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.sandbox = None

    def validate_context(self):
        if not self.sandbox:
            raise RuntimeError("Must enter a context to invoke apk")

    def configure_repos(self):
        self.validate_context()
        urls = pmb.helpers.repo.urls(user_repository=None, mirrors_exclude=[])
        repos = self.root_outer / "etc/apk/repositories"
        repos.parent.mkdir(exist_ok=True, parents=True)
        repos.open("w").write("\n".join([*urls, ""]))

    def add_pkgs(self, packages: list[str], *, initdb: bool = False) -> None:
        self.validate_context()
        self.sandbox.run(
            pmb.helpers.apk.prepare_cmd(
                ["add", *(["--initdb"] if initdb else []), *packages],
                Path("/work"),
                Path(self.root),
                self.arch,
            )
        )

    def del_pkgs(self, packages: list[str]) -> None:
        self.validate_context()
        self.sandbox.run(pmb.helpers.apk.prepare_cmd(["del", *packages]))


class ChrootSandbox(SandboxBase):
    """
    Sandbox running in Alpine container
    """

    __chroot: Chroot

    def __init__(self, chroot: Chroot, chdir: PathString | None = None, name: str = "", persistent: bool = False):
        """
        :param persistent: chroot rootfs directory isn't unique per-chdir
        """
        self.__chroot = Chroot(chroot.type, chroot.name, sandbox=True)
        self.persistent = persistent
        self.install_packages = ["alpine-base"]
        self.path = f"{self.__chroot.path}"
        if chdir and persistent:
            self.path += f"-{xhash(chdir + name or str(self.__chroot))}"
        work = str(get_context().config.work)
        super().__init__(
            name or str(self.__chroot),
            [
                BindOp(f"{work}/config_apk_keys", "/etc/apk/keys"),  # FIXME: readonly?
                BindOp(f"{work}/cache_apk_{chroot.arch}", "/var/cache/apk"),
                BindOp(f"{work}/cache_git", "/mnt/pmbootstrap/git"),
                BindOp(f"{work}/cache_ccache_{chroot.arch}", "/mnt/pmbootstrap/ccache"),
                BindOp(f"{work}/packages", "/mnt/pmbootstrap/packages"),
                TmpOp("/tmp"),
                EnvOp("PATH", "/bin:/sbin:/usr/bin:/usr/sbin"),
            ],
            uid=0,
            chdir=chdir,
        )


    def with_packages(self, packages: list[str]) -> Self:
        self.install_packages += packages
        return self


    @override
    def with_chdir(self, chdir: PathString | None) -> Self:
        if not self.persistent:
            self.path = f"{self.__chroot.path}" + f"-{xhash(chdir + self.name)}" if chdir is not None else ""
        return super().with_chdir(chdir)

    @override
    def build(self) -> Sandbox:
        path = Path(self.path)
        if not (path / "bin/sh").is_symlink():
            path.mkdir(exist_ok=True)
            with ApkTools(path, self.__chroot.arch) as apk:
                apk.configure_repos()
                apk.add_pkgs(self.install_packages, initdb=True)

        # We don't know the path for sure until now since it changes depending
        # on chdir. This way the chroot for each cwd is unique
        self.bind(self.path, "/")
        return super().build()
