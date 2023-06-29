# Copyright 2023 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import enum
from typing import Generator

class SuffixType(enum.Enum):
    ROOTFS = "rootfs"
    BUILDROOT = "buildroot"
    INSTALLER = "installer"
    NATIVE = "native"

    def __str__(self) -> str:
        return self.name

class Suffix:
    __type: SuffixType
    __name: str

    def __init__(self, suffix_type: SuffixType, name: str | None = ""):
        self.__type = suffix_type
        self.__name = name or ""
        if self.__type == SuffixType.NATIVE and len(self.__name) > 0:
            raise ValueError("The native suffix can't have a name")
        elif self.__type != SuffixType.NATIVE and len(self.__name) == 0:
            raise ValueError(f"The suffix type {self.__type} must have a name")

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
    
    @staticmethod
    def iter_patterns() -> Generator[str, None, None]:
        """
        Generate suffix patterns for all valid suffix types
        """
        for stype in SuffixType:
            if stype == SuffixType.NATIVE:
                yield f"chroot_{stype}"
            else:
                yield f"chroot_{stype}_*"
