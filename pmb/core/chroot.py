# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import enum
from collections.abc import Generator
from pathlib import Path, PosixPath, PurePosixPath
import pmb.config
from pmb.core.arch import Arch
from .context import get_context


class ChrootType(enum.Enum):
    ROOTFS = "rootfs"
    BUILDROOT = "buildroot"
    INSTALLER = "installer"
    NATIVE = "native"
    SYSROOT = "sysroot" # replaces native

    def __str__(self) -> str:
        return self.name


class Chroot:
    type_: ChrootType
    name_: str
    __channel: str | None

    def __init__(self, suffix_type: ChrootType, name: str | Arch | None = "") -> None:
        # We use the native chroot as the buildroot when building for the host arch
        if suffix_type == ChrootType.BUILDROOT and isinstance(name, Arch) and name.is_native():
            suffix_type = ChrootType.NATIVE
            name = ""

        self.type_ = suffix_type
        self.name_ = str(name or "")
        self.__channel = None

        self.__validate()

    def __validate(self) -> None:
        """
        Ensures that this suffix follows the correct format.
        """
        if self.type_ not in ChrootType._member_map_.values():
            raise ValueError(f"Invalid chroot type: '{self.type_}'")

        # A buildroot suffix must have a name matching one of alpines
        # architectures.
        if self.type_ == ChrootType.BUILDROOT and self.arch not in Arch.supported():
            raise ValueError(f"Invalid buildroot suffix: '{self.name_}'")

        # A rootfs or installer suffix must have a name matching a device.
        if self.type_ == ChrootType.INSTALLER or self.type_ == ChrootType.ROOTFS:
            # FIXME: pmb.helpers.devices.find_path() requires args parameter
            pass

        # A native suffix must not have a name.
        if self.type_ == ChrootType.NATIVE and self.name_ != "":
            raise ValueError(f"The native suffix can't have a name but got: '{self.name_}'")

        # rootfs suffixes must have a valid device name
        if self.type_ == ChrootType.ROOTFS and (len(self.name_) < 3 or "-" not in self.name_):
            raise ValueError(f"Invalid device name: '{self.name_}'")

    def __str__(self) -> str:
        if len(self.name_) > 0:
            return f"{self.type_.value}_{self.name_}"
        else:
            return self.type_.value

    @property
    def dirname(self) -> str:
        return f"chroot_{self}"

    @property
    def path(self) -> Path:
        return Path(get_context().config.work, self.dirname)

    def exists(self) -> bool:
        return (self / "bin/sh").is_symlink()

    def is_mounted(self) -> bool:
        return self.exists() and pmb.mount.ismount(self.path / "proc")

    @property
    def arch(self) -> Arch:
        if self.type in (ChrootType.NATIVE, ChrootType.SYSROOT):
            return Arch.native()
        if self.type == ChrootType.BUILDROOT:
            return Arch.from_str(self.name)
        # FIXME: this is quite delicate as it will only be valid
        # for certain pmbootstrap commands... It was like this
        # before but it should be fixed.
        arch = pmb.parse.deviceinfo().arch
        if arch is not None:
            return arch

        raise ValueError(f"Invalid chroot suffix: {self} (wrong device chosen in 'init' step?)")

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return str(self) == other or self.path == Path(other) or self.name == other

        if isinstance(other, PosixPath):
            return self.path == other

        if not isinstance(other, Chroot):
            return NotImplemented

        return self.type == other.type and self.name == other.name

    def __truediv__(self, other: object) -> Path:
        if isinstance(other, (PosixPath, PurePosixPath)):
            # Convert the other path to a relative path
            # FIXME: we should avoid creating absolute paths that we actually want
            # to make relative to the chroot...
            other = other.relative_to("/") if other.is_absolute() else other
            return self.path.joinpath(other)
        if isinstance(other, str):
            return self.path.joinpath(other.strip("/"))

        return NotImplemented

    def __rtruediv__(self, other: object) -> Path:
        if isinstance(other, (PosixPath, PurePosixPath)):
            # Important to produce a new Path object here, otherwise we
            # end up with one object getting shared around and modified
            # and lots of weird stuff happens.
            return Path(other) / self.path
        if isinstance(other, str):
            # This implicitly creates a new Path object
            return other / self.path

        return NotImplemented

    @property
    def type(self) -> ChrootType:
        return self.type_

    @property
    def name(self) -> str:
        return self.name_

    # FIXME: this feels unoptimised and hacky, we ought to know the channel
    # at the point where the chroot is created.
    @property
    def channel(self) -> str:
        """Release channel this chroot is using"""
        if not (self.path / "etc/os-release").exists():
            raise RuntimeError(f"({self}) Can't determine channel for unitialised chroot")

        for line in (self.path / "etc/os-release").open().readlines():
            if line.startswith("VERSION="):
                return line.removeprefix('VERSION="')[:-2]

        raise RuntimeError(f"({self}) Unable to determine release channel")

    @staticmethod
    def native() -> Chroot:
        # raise NotImplementedError("native chroot is removed")
        return Chroot(ChrootType.NATIVE)

    @staticmethod
    def sysroot() -> Chroot:
        return Sysroot()

    @staticmethod
    def buildroot(arch: Arch) -> Chroot:
        return Chroot(ChrootType.BUILDROOT, arch)

    @staticmethod
    def rootfs(device: str) -> Chroot:
        return Chroot(ChrootType.ROOTFS, device)

    @staticmethod
    def from_str(s: str) -> Chroot:
        """
        Generate a Suffix from a suffix string like "buildroot_aarch64"
        """
        parts = s.split("_", 1)
        stype = parts[0]

        if len(parts) == 2:
            # Will error if stype isn't a valid ChrootType
            # The name will be validated by the Chroot constructor
            return Chroot(ChrootType(stype), parts[1])

        # "native" is the only valid suffix type, the constructor(s)
        # will validate that stype is "native"
        return Chroot(ChrootType(stype))

    @staticmethod
    def iter_patterns() -> Generator[str, None, None]:
        """
        Generate suffix patterns for all valid suffix types
        """
        for stype in ChrootType:
            if stype == ChrootType.NATIVE:
                yield f"chroot_{stype.value}"
            else:
                yield f"chroot_{stype.value}_*"

    @staticmethod
    def glob(pat: str = "") -> Generator[Path, None, None]:
        """
        Glob all initialized chroot directories.
        :param pat: pattern to match in chroot (e.g. "/in-pmbootstrap")
        """
        for pattern in Chroot.iter_patterns():
            yield from Path(get_context().config.work).glob(pattern + pat)


    @staticmethod
    def all_active() -> Generator[Chroot, None, None]:
        """
        Iterate over all active chroots that have the /in-pmbootstrap flag
        """
        for path in Chroot.glob("/in-pmbootstrap"):
            yield Chroot.from_str(path.parent.name.removeprefix("chroot_"))


# This lets us treat the sysroot as a Chroot prior to entering the mount namespace
class Sysroot(Chroot):
    def __init__(self):
        self.type_ = ChrootType.SYSROOT
        self.name_ = "sysroot"


    @property
    def dirname(self) -> str:
        return "sysroot"


    @property
    def path(self) -> Path:
        return get_context().config.work / "sysroot"
