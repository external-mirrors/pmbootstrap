# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later

import tarfile
from pathlib import PosixPath

from pmb.core.apk_package import ApkPackage


# pathlib.Path can only be directly subclassed since python3.12
class Apkindex(PosixPath):
    """An APKINDEX file."""

    def read_lines(self) -> list[str]:
        if tarfile.is_tarfile(self):
            with (
                tarfile.open(self, "r:gz") as tar,
                tar.extractfile(tar.getmember("APKINDEX")) as handle,  # type:ignore[union-attr]
            ):
                return handle.read().decode().split("\n\n")
        else:
            with self.open("r", encoding="utf-8") as handle:
                return handle.read().split("\n\n")

    def get_apk_packages(self) -> list[ApkPackage]:
        """
        Read all blocks from the APKINDEX a list.

        :returns: all blocks in the APKINDEX, without restructuring them by
                  pkgname or removing duplicates with lower versions.
        """
        return [
            ApkPackage.from_apkindex_block(b.strip().splitlines())
            for b in self.read_lines()
            if len(b.strip()) > 0
        ]
