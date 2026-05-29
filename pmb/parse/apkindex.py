# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import tarfile
from pathlib import Path
from typing import Literal, cast, overload

import pmb.helpers.package
import pmb.helpers.repo
import pmb.parse.version
from pmb.core.apkindex_block import ApkindexBlock
from pmb.core.arch import Arch
from pmb.helpers import logging


def _add_block_from_provides(
    ret: dict[str, dict[str, ApkindexBlock]],
    block: ApkindexBlock,
    provide: str | None = None,
) -> None:
    """
    Add one block to the return dictionary of parse().

    :param ret: dictionary of all packages in the APKINDEX that is
                getting built right now. This function will extend it.
    :param block: an ApkindexBlock to potentially add to ret.
    :param provide: defaults to the pkgname, could be a provide from the
                    "provides" list.
    """
    # Defaults
    pkgname = block.pkgname
    provide = provide or pkgname

    block_old = None
    # Ignore the block, if the block we already have has a higher version
    if provide in ret and pkgname in ret[provide]:
        block_old = ret[provide][pkgname]
        version_old = block_old.version
        version_new = block.version
        if pmb.parse.version.compare(version_old, version_new) == 1:
            return

    # Add it to the result set
    if provide not in ret:
        ret[provide] = {}
    ret[provide][pkgname] = block


def _add_block_from_pkgname(
    ret: dict[str, ApkindexBlock],
    block: ApkindexBlock,
) -> None:
    """
    Add one block to the return dictionary of parse().

    :param ret: dictionary of all packages in the APKINDEX that is
                getting built right now. This function will extend it.
    :param block: an ApkindexBlock to potentially add to ret.
    """
    pkgname = block.pkgname

    # Don't add it if a block with a newer version exists
    if pkgname in ret:
        block_old = ret[pkgname]
        version_old = block_old.version
        version_new = block.version
        if pmb.parse.version.compare(version_old, version_new) == 1:
            return

    ret[pkgname] = block


@overload
def parse(path: Path) -> dict[str, dict[str, ApkindexBlock]]: ...


@overload
def parse(path: Path, multiple_providers: Literal[False] = ...) -> dict[str, ApkindexBlock]: ...


@overload
def parse(
    path: Path, multiple_providers: Literal[True] = ...
) -> dict[str, dict[str, ApkindexBlock]]: ...


def parse(
    path: Path, multiple_providers: bool = True
) -> dict[str, ApkindexBlock] | dict[str, dict[str, ApkindexBlock]]:
    r"""
    Parse an APKINDEX.tar.gz file, and return its content as dictionary.

    :param path: path to an APKINDEX.tar.gz file or apk package database
                 (almost the same format, but not compressed).
    :param multiple_providers: assume that there are more than one provider for
                               the package. This makes sense when parsing the
                               APKINDEX files from a repository (#1122), but
                               not when parsing apk's installed packages DB.
    :returns: (without multiple_providers)

    Generic format:
        ``{ pkgname: ApkindexBlock, ... }``

    Example:
        ``{ "postmarketos-mkinitfs": ApkindexBlock, "so:libGL.so.1": ApkindexBlock, ...}``

    :returns: (with multiple_providers)

    Generic format:
        ``{ provide: { pkgname: ApkindexBlock, ... }, ... }``

    Example:
        ``{ "postmarketos-mkinitfs": {"postmarketos-mkinitfs": ApkindexBlock},"so:libGL.so.1": {"mesa-egl": ApkindexBlock, "libhybris": ApkindexBlock}, ...}``
    """
    # Require the file to exist
    if not path.is_file():
        logging.verbose(
            "NOTE: APKINDEX not found, assuming no binary packages"
            f" exist for that architecture: {path}"
        )
        return {}

    # Try to get a cached result first
    lastmod = path.lstat().st_mtime
    cache_key_ = "multiple" if multiple_providers else "single"
    key = cache_key(path)
    if key in pmb.helpers.other.cache["apkindex"]:
        cache = pmb.helpers.other.cache["apkindex"][key]
        if cache["lastmod"] == lastmod:
            if cache_key_ in cache:
                return cache[cache_key_]
        else:
            clear_cache(path)

    # Read all lines
    block_lines: list[str]
    if tarfile.is_tarfile(path):
        with (
            tarfile.open(path, "r:gz") as tar,
            tar.extractfile(tar.getmember("APKINDEX")) as handle,  # type:ignore[union-attr]
        ):
            block_lines = handle.read().decode().split("\n\n")
    else:
        with path.open("r", encoding="utf-8") as handle:
            block_lines = handle.read().split("\n\n")

    # The APKINDEX might be empty, for example if you run "pmbootstrap index" and have no local
    # packages
    if not block_lines:
        return {}

    # Parse the whole APKINDEX file
    ret: dict[str, ApkindexBlock] = collections.OrderedDict()
    if multiple_providers:
        ret = cast(dict[str, dict[str, ApkindexBlock]], ret)

    for block_line in block_lines:
        block_line = block_line.strip()
        if len(block_line) == 0:
            continue
        block = ApkindexBlock(block_line.splitlines())
        # Skip virtual packages
        if block.timestamp is None:
            logging.verbose(f"Skipped virtual package {block} in file: {path}")
            continue

        if multiple_providers:
            _add_block_from_provides(ret, block, None)
            for provide in block.provides:
                _add_block_from_provides(ret, block, provide)
        else:
            _add_block_from_pkgname(ret, block)

    # Update the cache
    key = cache_key(path)
    if key not in pmb.helpers.other.cache["apkindex"]:
        pmb.helpers.other.cache["apkindex"][key] = {"lastmod": lastmod}
    pmb.helpers.other.cache["apkindex"][key][cache_key_] = ret
    return ret


def parse_blocks(path: Path) -> list[ApkindexBlock]:
    """
    Read all blocks from an APKINDEX.tar.gz into a list.

    :path: full path to the APKINDEX.tar.gz file.
    :returns: all blocks in the APKINDEX, without restructuring them by
              pkgname or removing duplicates with lower versions (use
              parse() if you need these features).
    """
    # Parse all lines
    with tarfile.open(path, "r:gz") as tar, tar.extractfile(tar.getmember("APKINDEX")) as handle:  # type:ignore[union-attr]
        block_lines = handle.read().decode().split("\n\n")

    # Parse lines into blocks
    ret = [ApkindexBlock(b.strip().splitlines()) for b in block_lines]

    return ret


# FIXME: come up with something better here...
def cache_key(path: Path) -> int:
    return hash(path)


def clear_cache(path: Path) -> bool:
    """
    Clear the APKINDEX parsing cache.

    :returns: True on successful deletion, False otherwise
    """
    key = cache_key(path)
    logging.verbose(f"Clear APKINDEX cache for: {key}")
    if key in pmb.helpers.other.cache["apkindex"]:
        del pmb.helpers.other.cache["apkindex"][key]
        return True
    else:
        logging.verbose(
            "Nothing to do, path was not in cache:"
            + str(pmb.helpers.other.cache["apkindex"].keys())
        )
        return False


def providers(
    package: str,
    arch: Arch | None = None,
    must_exist: bool = True,
    indexes: list[Path] | None = None,
    user_repository: bool = True,
) -> dict[str, ApkindexBlock]:
    """
    Get all packages, which provide one package.

    :param package: of which you want to have the providers
    :param arch: defaults to native arch, only relevant for indexes=None
    :param must_exist: When set to true, raise an exception when the package is
                       not provided at all.
    :param indexes: list of APKINDEX.tar.gz paths, defaults to all index files
                    (depending on arch)
    :param user_repository: add path to index of locally built packages
    :returns: list of parsed packages. Example for package="so:libGL.so.1":
        ``{"mesa-egl": ApkindexBlock, "libhybris": ApkindexBlock}``
    """
    if not indexes:
        indexes = pmb.helpers.repo.apkindex_files(arch, user_repository=user_repository)

    pkgname_with_op = package
    package = pmb.helpers.package.remove_operators(pkgname_with_op)

    ret: dict[str, ApkindexBlock] = collections.OrderedDict()
    for path in indexes:
        # Skip indexes not providing the package
        index_packages = parse(path)
        if package not in index_packages:
            continue

        indexed_package = index_packages[package]

        # Iterate over found providers
        for provider_pkgname, provider in indexed_package.items():
            version = provider.version
            if not pmb.helpers.package.check_version_constraints(pkgname_with_op, version):
                continue
            # Skip lower versions of providers we already found
            if provider_pkgname in ret:
                version_last = ret[provider_pkgname].version
                if pmb.parse.version.compare(version, version_last) == -1:
                    logging.verbose(
                        f"{package}: provided by: {provider_pkgname}-{version}"
                        f"in {path} (but {version_last} is higher)"
                    )
                    continue

            # Add the provider to ret
            logging.verbose(f"{package}: provided by: {provider_pkgname}-{version} in {path}")
            ret[provider_pkgname] = provider

    if ret == {} and must_exist:
        import os

        logging.debug(f"Searched in APKINDEX files: {', '.join([os.fspath(x) for x in indexes])}")
        raise RuntimeError("Could not find package '" + package + "'!")

    return ret


def provider_highest_priority(
    providers: dict[str, ApkindexBlock], pkgname: str
) -> dict[str, ApkindexBlock]:
    """
    Get the provider(s) with the highest provider_priority and log a message.

    :param providers: returned dict from providers(), must not be empty
    :param pkgname: the package name we are interested in (for the log message)
    """
    max_priority = 0
    priority_providers: collections.OrderedDict[str, ApkindexBlock] = collections.OrderedDict()
    for provider_name, provider in providers.items():
        priority = int(-1 if provider.provider_priority is None else provider.provider_priority)
        if priority > max_priority:
            priority_providers.clear()
            max_priority = priority
        if priority == max_priority:
            priority_providers[provider_name] = provider

    if priority_providers:
        logging.debug(
            f"{pkgname}: picked provider(s) with highest priority "
            f"{max_priority}: {', '.join(priority_providers.keys())}"
        )
        return priority_providers

    # None of the providers seems to have a provider_priority defined
    return providers


def provider_shortest(providers: dict[str, ApkindexBlock], pkgname: str) -> ApkindexBlock:
    """
    Get the provider with the shortest pkgname and log a message. In most cases
    this should be sufficient, e.g. 'mesa-purism-gc7000-egl, mesa-egl' or
    'gtk+2.0-maemo, gtk+2.0'.

    :param providers: returned dict from providers(), must not be empty
    :param pkgname: the package name we are interested in (for the log message)
    """
    ret = min(list(providers.keys()), key=len)
    if len(providers) != 1:
        logging.debug(
            f"{pkgname}: has multiple providers ("
            f"{', '.join(providers.keys())}), picked shortest: {ret}"
        )
    return providers[ret]


# This can't be cached because the APKINDEX can change during pmbootstrap build!
def package(
    package: str,
    arch: Arch | None = None,
    must_exist: bool = True,
    indexes: list[Path] | None = None,
    user_repository: bool = True,
) -> ApkindexBlock | None:
    """
    Get a specific package's data from an apkindex.

    :param package: of which you want to have the apkindex data
    :param arch: defaults to native arch, only relevant for indexes=None
    :param must_exist: When set to true, raise an exception when the package is
                       not provided at all.
    :param indexes: list of APKINDEX.tar.gz paths, defaults to all index files
                    (depending on arch)
    :param user_repository: add path to index of locally built packages
    :returns: ApkindexBlock or None when the package was not found.
    """
    # Provider with the same package
    package_providers = providers(
        package, arch, must_exist, indexes, user_repository=user_repository
    )

    if package_providers:
        providers_priority = provider_highest_priority(package_providers, package)
        num_providers = len(providers_priority)
        # Only one provider with max priority: return it
        if num_providers == 1:
            return next(iter(providers_priority.values()))
        # Multiple providers with max priority: let follow-on logic decide
        elif num_providers > 1:
            package_providers = providers_priority

    # Any provider
    if package_providers:
        return pmb.parse.apkindex.provider_shortest(package_providers, package)

    # No provider
    if must_exist:
        raise RuntimeError("Package '" + package + "' not found in any APKINDEX.")
    return None
