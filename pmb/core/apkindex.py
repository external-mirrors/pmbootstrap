# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import PosixPath


# pathlib.Path can only be directly subclassed since python3.12
class Apkindex(PosixPath):
    """An APKINDEX file."""

    pass
