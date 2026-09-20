# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import shlex
from pathlib import Path

import pmb.helpers.run
from pmb.helpers import logging


class ApkRepo:
    _repos_file = "etc/apk/repositories"

    def __init__(self, url: str | Path) -> None:
        self._url = str(url)

    def __str__(self) -> str:
        return self._url

    def __eq__(self, o) -> bool:
        if not isinstance(o, ApkRepo):
            return False
        else:
            return self._url == o._url

    @classmethod
    def from_repositories_file(cls, root: Path) -> list[ApkRepo]:
        path = root / cls._repos_file
        repos: list[ApkRepo] = []
        if path.exists():
            with path.open() as handle:
                repos.extend(cls(line[:-1]) for line in handle)
        return repos

    @staticmethod
    def write_repositories_file(root: Path, repos: list[ApkRepo]) -> None:
        path = root / ApkRepo._repos_file
        logging.debug(f"({root.name}) update /etc/apk/repositories")
        if path.exists():
            pmb.helpers.run.root(["rm", path])
        else:
            pmb.helpers.run.root(["mkdir", "-p", path.parent])
        for line in repos:
            pmb.helpers.run.root(["sh", "-c", f"echo {shlex.quote(str(line))} >> {path}"])
