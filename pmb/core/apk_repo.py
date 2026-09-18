# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path


class ApkRepo:
    def __init__(self, url: str | Path) -> None:
        self._url = str(url)

    def __str__(self) -> str:
        return self._url

    def __eq__(self, o) -> bool:
        if not isinstance(o, ApkRepo):
            return False
        else:
            return self._url == o._url
