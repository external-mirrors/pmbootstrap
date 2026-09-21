# Copyright 2026 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import os.path
import shlex
from pathlib import Path
from urllib.parse import urlsplit

import pmb.config.pmaports
import pmb.helpers.run
from pmb.core.apkindex import Apkindex
from pmb.core.arch import Arch
from pmb.core.context import get_context
from pmb.core.pkgrepo import pkgrepo_names
from pmb.helpers import logging


class ApkRepo:
    _repos_file = "etc/apk/repositories"

    def __init__(self, url: str | Path) -> None:
        self._url = str(url)
        self._remote = True
        if urlsplit(self._url).scheme == "":
            self._remote = False

    def __str__(self) -> str:
        return self._url

    def __eq__(self, o) -> bool:
        if not isinstance(o, ApkRepo):
            return False
        else:
            return self._url == o._url

    def hash(self, length: int = 8) -> str:
        r"""
        Generate the hash that APK adds to the APKINDEX and apk packages in its apk cache folder.

        It is the "12345678" part in this example:
        "APKINDEX.12345678.tar.gz".

        :param length: The length of the hash in the output file.

        See also: official implementation in apk-tools:
        <https://git.alpinelinux.org/cgit/apk-tools/>

        blob.c: apk_blob_push_hexdump(), "const char \\*xd"
        apk_defines.h: APK_CACHE_CSUM_BYTES
        database.c: apk_repo_format_cache_index()
        """
        binary = hashlib.sha1(self._url.encode("utf-8"), usedforsecurity=False).digest()
        xd = "0123456789abcdefghijklmnopqrstuvwxyz"
        csum_bytes = int(length / 2)

        ret = ""
        for i in range(csum_bytes):
            ret += xd[(binary[i] >> 4) & 0xF]
            ret += xd[binary[i] & 0xF]

        return f"APKINDEX.{ret}.tar.gz"

    @classmethod
    def from_repositories_file(cls, root: Path) -> list[ApkRepo]:
        path = root / cls._repos_file
        repos: list[ApkRepo] = []
        if path.exists():
            with path.open() as handle:
                repos.extend(cls(line[:-1]) for line in handle)
        return repos

    @classmethod
    def get_local(cls, root: Path) -> list[ApkRepo]:
        return [cls(root / channel) for channel in pmb.config.pmaports.all_channels()]

    @classmethod
    def get_from_config(cls) -> list[ApkRepo]:
        ret: list[ApkRepo] = []
        config = get_context().config

        # Get mirrordirs from channels.cfg (postmarketOS mirrordir is the same as
        # the pmaports branch of the channel, no need to make it more complicated)
        channel_cfg = pmb.config.pmaports.read_config_channel()
        release_pmos = channel_cfg["branch_pmaports"]
        release_alpine = channel_cfg["mirrordir_alpine"]

        # ["pmaports", "systemd", "alpine"]
        for repo in [*pkgrepo_names(), "alpine"]:
            # Allow adding a custom mirror in front of the real mirror. This is used
            # in bpo to build with a WIP repository in addition to the final
            # repository.
            for suffix in ["_custom", ""]:
                mirror = config.mirrors[f"{repo}{suffix}"]

                # If repo is disabled (e.g: during bootstrap), skip it
                if mirror.lower() == "none":
                    continue

                if repo == "alpine":
                    alpine_repos = [f"{release_alpine}/main", f"{release_alpine}/community"]
                    if release_alpine == "edge":
                        alpine_repos.append(f"{release_alpine}/testing")
                    ret.extend(cls(os.path.join(mirror, r)) for r in alpine_repos)
                else:
                    ret.append(cls(os.path.join(mirror, release_pmos)))

        return ret

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

    def get_index(self, arch: Arch) -> Apkindex:
        path: Path
        if self._remote is True:
            path = get_context().config.work / f"cache_apk_{arch}" / self.hash()
        else:
            path = self._url / arch / "APKINDEX.tar.gz"
        return Apkindex(path)
