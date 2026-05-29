# Copyright 2024 Stefan Hansson
# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from pmb.core.arch import Arch

apkindex_map = {
    "A": "arch",
    "D": "depends",
    "o": "origin",
    "P": "pkgname",
    "p": "provides",
    "k": "provider_priority",
    "t": "timestamp",
    "V": "version",
}

required_apkindex_keys = ["arch", "pkgname", "version"]


class ApkindexBlock:
    """A representation of a package block as parsed from APKINDEX file."""

    def __init__(self, block_lines: list[str]):
        ret: dict[str, Any] = {}
        required_found = 0  # Count the required keys we found
        for line in block_lines:
            # Parse keys from the mapping
            key = apkindex_map.get(line[0])
            if not key:
                continue
            if key in ret:
                raise RuntimeError(f"Key {key} specified twice in block: {ret}")
            if key in required_apkindex_keys:
                required_found += 1
            ret[key] = line[2:]
        # Check for required keys
        if required_found != len(required_apkindex_keys):
            for key in required_apkindex_keys:
                if key not in ret:
                    raise RuntimeError(f"Missing required key '{key}' in block {ret}")
            raise RuntimeError(
                f"Expected {len(required_apkindex_keys)} required keys,"
                f" but found {required_found} in block: {ret}"
            )

        # Format optional lists
        for key in ["provides", "depends"]:
            if key in ret and ret[key] != "":
                # Ignore all operators for now
                values = ret[key].split(" ")
                ret[key] = []
                for value in values:
                    for operator in [">", "=", "<", "~"]:
                        if operator in value:
                            value = value.split(operator)[0]
                            break
                    ret[key].append(value)
            else:
                ret[key] = []
        provider_priority = ret.get("provider_priority")
        if provider_priority:
            if not provider_priority.isdigit():
                raise RuntimeError(
                    f"Invalid provider_priority: '{provider_priority}' parsing block {ret}"
                )
            provider_priority = int(provider_priority)
        else:
            provider_priority = None

        self._block = ret
        self._block["provider_priority"] = provider_priority
        self._block["arch"] = Arch.from_str(ret["arch"])

    @property
    def arch(self) -> Arch:
        """The architecture of the package."""
        return self._block["arch"]

    @property
    def depends(self) -> list[str]:
        """Dependencies for the package."""
        return self._block["depends"]

    @property
    def origin(self) -> str | None:
        """
        The origin name of the package.

        This is unset in virtual packages.
        """
        return self._block.get("origin")

    @property
    def pkgname(self) -> str:
        """The package name."""
        return self._block["pkgname"]

    @property
    def provides(self) -> list[str]:
        """The package providers."""
        return self._block["provides"]

    @property
    def provider_priority(self) -> int | None:
        """The provider priority for the package."""
        return self._block["provider_priority"]

    @property
    def timestamp(self) -> str | None:
        """
        The unix timestamp of the package build date/time.

        This is unset in virtual packages.
        """
        return self._block.get("timestamp")

    @property
    def version(self) -> str:
        """The package version."""
        return self._block["version"]
