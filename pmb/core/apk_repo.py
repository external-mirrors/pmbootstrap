# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path


class ApkRepo:
    def __init__(self, url: str | Path) -> None:
        self._url = str(url)

    def __str__(self) -> str:
        return self._url
