# Copyright 2024 Stefan Hansson
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from pmb.core.apk_package import ApkPackage
from pmb.core.arch import Arch
from pmb.types import Apkbuild


@dataclass
class PackageMetadata:
    arch: Arch
    depends: list[str]
    pkgname: str
    provides: list[str]
    version: str
    from_pmaports: bool

    @staticmethod
    def from_apkindex_block(apkindex_block: ApkPackage) -> PackageMetadata:
        return PackageMetadata(
            arch=apkindex_block.arch,
            depends=apkindex_block.depends,
            pkgname=apkindex_block.pkgname,
            provides=apkindex_block.provides,
            version=apkindex_block.version,
            from_pmaports=False,
        )

    @staticmethod
    def from_pmaport(pmaport: Apkbuild, arch: Arch) -> PackageMetadata:
        pmaport_depends = pmaport["depends"]
        pmaport_pkgname = pmaport["pkgname"]
        pmaport_provides = pmaport["provides"]
        pmaport_version = pmaport["pkgver"] + "-r" + pmaport["pkgrel"]

        return PackageMetadata(
            arch=arch,
            depends=pmaport_depends or [],
            pkgname=pmaport_pkgname,
            provides=pmaport_provides,
            version=pmaport_version,
            from_pmaports=True,
        )
