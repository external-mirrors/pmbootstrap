# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pmb.core.arch import Arch
from pmb.helpers import logging
import shutil
import tarfile
import tempfile
import stat
from pathlib import Path

import pmb.helpers.apk
import pmb.helpers.run
import pmb.helpers.repo
import pmb.config
import pmb.config.file
import pmb.parse.apkindex
import pmb.helpers.http
import pmb.parse.version
from pmb.core.context import get_context


def read_signature_info(tar: tarfile.TarFile) -> tuple[str, str]:
    """
    Find various information about the signature that was used to sign
    /sbin/apk.static inside the archive (not to be confused with the normal apk
    archive signature!)

    :returns: (sigfilename, sigkey_path)
    """
    # Get signature filename and key
    prefix = "sbin/apk.static.SIGN.RSA.sha256."
    sigfilename = None
    for filename in tar.getnames():
        if filename.startswith(prefix):
            sigfilename = filename
            break
    if not sigfilename:
        raise RuntimeError(
            "Could not find signature filename in apk."
            " This means that your apk file is damaged."
            " Delete it and try again."
            " If the problem persists, fill out a bug report."
        )
    sigkey = sigfilename[len(prefix) :]
    logging.debug(f"sigfilename: {sigfilename}")
    logging.debug(f"sigkey: {sigkey}")

    # Get path to keyfile on disk
    sigkey_path = f"{pmb.config.apk_keys_path}/{sigkey}"
    if "/" in sigkey or not os.path.exists(sigkey_path):
        logging.debug(f"sigkey_path: {sigkey_path}")
        raise RuntimeError(f"Invalid signature key: {sigkey}")

    return (sigfilename, sigkey_path)


def extract_temp(tar: tarfile.TarFile, sigfilename: str) -> dict[str, dict]:
    """
    Extract apk.static and signature as temporary files.
    """
    ret = {
        "apk": {"filename": "sbin/apk.static", "temp_path": None},
        "sig": {"filename": sigfilename, "temp_path": None},
    }
    for ftype in ret.keys():
        filename = ret[ftype]["filename"]
        if filename is None:
            raise AssertionError
        member = tar.getmember(filename)

        fd, path = tempfile.mkstemp(ftype, "pmbootstrap")
        handle = open(fd, "wb")
        ret[ftype]["temp_path"] = path
        extracted_file = tar.extractfile(member)
        if extracted_file is None:
            raise AssertionError
        shutil.copyfileobj(extracted_file, handle)

        logging.debug(f"extracted: {path}")
        handle.close()
    return ret


def verify_signature(files: dict[str, dict], sigkey_path: str) -> None:
    """
    Verify the signature with openssl.

    :param files: return value from extract_temp()
    :raises RuntimeError: when verification failed and  removes temp files
    """
    logging.debug(f"Verify apk.static signature with {sigkey_path}")
    try:
        pmb.helpers.run.user(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                sigkey_path,
                "-signature",
                files["sig"]["temp_path"],
                files["apk"]["temp_path"],
            ]
        )
    except BaseException:
        os.unlink(files["sig"]["temp_path"])
        os.unlink(files["apk"]["temp_path"])
        raise RuntimeError(
            "Failed to validate signature of apk.static."
            " Either openssl is not installed, or the"
            " download failed. Run 'pmbootstrap zap -hc' to"
            " delete the download and try again."
        )


def extract(version: str, apk_path: Path) -> None:
    """
    Extract everything to temporary locations, verify signatures and reported
    versions. When everything is right, move the extracted apk.static to the
    final location.
    """
    # Extract to a temporary path
    with tarfile.open(apk_path, "r:gz") as tar:
        sigfilename, sigkey_path = read_signature_info(tar)
        files = extract_temp(tar, sigfilename)

    # Verify signature
    verify_signature(files, sigkey_path)
    os.unlink(files["sig"]["temp_path"])
    temp_path = files["apk"]["temp_path"]

    # Verify the version that the extracted binary reports
    logging.debug(
        "Verify the version reported by the apk.static binary"
        f" (must match the package version {version})"
    )
    os.chmod(temp_path, os.stat(temp_path).st_mode | stat.S_IEXEC)
    version_bin = pmb.helpers.run.user_output([temp_path, "--version"])
    version_bin = version_bin.split(" ")[1].split(",")[0]
    if not version.startswith(f"{version_bin}-r"):
        os.unlink(temp_path)
        raise RuntimeError(
            f"Downloaded apk-tools-static-{version}.apk,"
            " but the apk binary inside that package reports"
            f" to be version: {version_bin}!"
            " Looks like a downgrade attack"
            " from a malicious server! Switch the server (-m)"
            " and try again."
        )

    # Move it to the right path
    target_path = get_context().config.work / "apk.static"
    shutil.move(temp_path, target_path)


def download(file: str) -> Path:
    """
    Download a single file from an Alpine mirror.
    """
    channel_cfg = pmb.config.pmaports.read_config_channel()
    mirrordir = channel_cfg["mirrordir_alpine"]
    base_url = f"{get_context().config.mirrors['alpine']}{mirrordir}/main/{Arch.native()}"
    return pmb.helpers.http.download(f"{base_url}/{file}", file)


def init() -> None:
    """
    Download, verify, extract $WORK/apk.static.
    """
    # Get and parse the APKINDEX. alpine_apkindex_path() will implicitly
    # download the APKINDEX file if it's missing.
    apkindex = pmb.helpers.repo.alpine_apkindex_path("main")
    index_data = pmb.parse.apkindex.package("apk-tools-static", indexes=[apkindex])

    if index_data is None:
        raise RuntimeError("Could not find apk-tools-static in APKINDEX!")

    version = index_data.version

    # Verify the apk-tools-static version
    pmb.helpers.apk.check_outdated(version, "Run 'pmbootstrap update', then try again.")

    # Download, extract, verify apk-tools-static
    apk_name = f"apk-tools-static-{version}.apk"
    apk_static = download(apk_name)
    extract(version, apk_static)
