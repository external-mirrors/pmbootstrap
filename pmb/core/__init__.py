# Copyright 2023 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import enum
import logging

import pmb.helpers.devices

class SuffixType(enum.Enum):
    """
    A suffix type defines roughly what this chroot is for.

    rootfs: A device rootfs to be installed onto a device.
    buildroot: A chroot for building packages for a specific arch.
    installer: A chroot for building an installer for a specific device.
    native: The chroot used for tasks that need to run on the host.
    """
    ROOTFS = "rootfs"
    BUILDROOT = "buildroot"
    INSTALLER = "installer"
    NATIVE = "native"

    def __str__(self) -> str:
        return self.name

class Suffix:
    """
    Represents a chroot suffix string, this string is used to access
    a specific chroot and must follow a consistent format.

    A suffix string is one of:

     -> (rootfs | installer) '_' CODENAME
     -> buildroot '_' (x86 | x86_64 | aarch64 | armhf | armv7)
     -> native

    Where CODENAME is the codename of a device in the format:

     -> VENDOR '-' CODENAME
    """
    __type: SuffixType
    __name: str

    def __init__(self, suffix_type: SuffixType, name: str | None = ""):
        self.__type = suffix_type
        self.__name = name or ""

        self.__validate()

    def __validate(self) -> None:
        """
        Ensures that this suffix follows the correct format.
        """
        valid_arches = [
            "x86",
            "x86_64",
            "aarch64",
            "armhf", # XXX: remove this?
            "armv7",
            "riscv64",
        ]

        # A buildroot suffix must have a name matching one of alpines
        # architectures.
        if self.__type == SuffixType.BUILDROOT and self.__name not in valid_arches:
            raise ValueError(f"Invalid buildroot suffix: '{self.__name}'")

        # A rootfs or installer suffix must have a name matching a device.
        if self.__type == SuffixType.INSTALLER or self.__type == SuffixType.ROOTFS:
            if not pmb.helpers.devices.find_path(self.__name):
                logging.warn(f"Suffix is for invalid device: '{self.__name}'")

        # A native suffix must not have a name.
        if self.__type == SuffixType.NATIVE and self.__name != "":
            raise ValueError(f"The native suffix can't have a name but got: "
                             f"'{self.__name}'")

    # Prefer .chroot()
    def __str__(self) -> str:
        if len(self.__name) > 0:
            return f"{self.__type.value}_{self.__name}"
        else:
            return self.__type.value
    
    def chroot(self) -> str:
        return f"chroot_{self}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Suffix):
            return NotImplemented

        return self.type() == other.type() and self.name() == other.name()

    def type(self) -> SuffixType:
        return self.__type

    def name(self) -> str:
        return self.__name

    @staticmethod
    def native() -> Suffix:
        return Suffix(SuffixType.NATIVE)

    @staticmethod
    def from_str(s: str) -> Suffix:
        """
        Generate a Suffix from a suffix string like "buildroot_aarch64"
        """
        parts = s.split("_", 1)
        stype = parts[0]

        if len(parts) == 2:
            # Will error if stype isn't a valid SuffixType
            # The name will be validated by the Suffix constructor
            return Suffix(SuffixType(stype), parts[1])

        # "native" is the only valid suffix type, the constructor(s)
        # will validate that stype is "native"
        return Suffix(SuffixType(stype))