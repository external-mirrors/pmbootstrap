# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any, Literal, TypedDict

from pmb.core.arch import Arch
from pmb.core.chroot import Chroot

import uuid


class CrossCompile(enum.Enum):
    # Cross compilation isn't needed for this package:
    # 1) Either because the arch we will build for is exactly the same as the
    #    native arch, or
    # 2) because CPU emulation is not needed (e.g. x86 on x86_64)
    UNNECESSARY = "unnecessary"
    # Cross compilation disabled, only use QEMU
    QEMU_ONLY = "qemu-only"
    # Cross compilation will use crossdirect
    CROSSDIRECT = "crossdirect"
    # Cross compilation will use cross-native
    CROSS_NATIVE = "cross-native"
    # Cross compilation will use cross-native2
    CROSS_NATIVE2 = "cross-native2"

    def __str__(self) -> str:
        return self.value

    def enabled(self) -> bool:
        """Are we cross-compiling for this value of cross?"""
        return self not in [CrossCompile.UNNECESSARY, CrossCompile.QEMU_ONLY]

    def host_chroot(self, arch: Arch) -> Chroot:
        """Chroot for the package target architecture (the "host" machine).
        Cross native (v1) is the exception, since we exclusively use the native
        chroot for that."""
        if arch == Arch.native():
            return Chroot.native()

        match self:
            case CrossCompile.CROSS_NATIVE:
                return Chroot.native()
            case _:
                return Chroot.buildroot(arch)

    def build_chroot(self, arch: Arch) -> Chroot:
        """Chroot for the package build architecture (the "build" machine)."""
        if arch == Arch.native():
            return Chroot.native()

        match self:
            case CrossCompile.UNNECESSARY | CrossCompile.CROSSDIRECT | CrossCompile.QEMU_ONLY:
                return Chroot.buildroot(arch)
            case CrossCompile.CROSS_NATIVE | CrossCompile.CROSS_NATIVE2:
                return Chroot.native()


class DiskPartition:
    name: str
    size: int  # in bytes
    filesystem: str | None
    # offset into the disk image!
    offset: int  # bytes
    path: str  # e.g. /dev/install or /dev/installp1 for --split
    _uuid: str

    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size
        self.filesystem = None
        self.offset = 0
        self.path = ""
        self._uuid = ""

    @property
    def uuid(self) -> str:
        """
        We generate a UUID the first time we're called. The length
        depends on which filesystem, since FAT only supported short
        volume IDs.
        """
        if self.filesystem is None:
            raise ValueError("Can't get UUID when filesystem not set")

        if self._uuid:
            return self._uuid

        if self.filesystem.startswith("fat"):
            # FAT UUIDs are only 8 bytes and are always uppercase
            self._uuid = ("-".join(str(uuid.uuid4()).split("-")[1:3])).upper()
        else:
            self._uuid = str(uuid.uuid4())

        return self._uuid

    @property
    def size_mb(self) -> int:
        return round(self.size / (1024**2))

    @property
    def partition_label(self) -> str:
        return f"pmOS_{self.name}"

    def offset_sectors(self, sector_size: int) -> int:
        if self.offset % sector_size != 0:
            raise ValueError(
                f"Partition {self.name} offset not a multiple of sector size {sector_size}!"
            )
        return int(self.offset / sector_size)

    def size_sectors(self, sector_size: int) -> int:
        ss = int((self.size + sector_size) / sector_size)
        # sgdisk requires aligning to 2048-sector boundaries.
        # It conservatively rounds down but we want to round up...
        ss = int((ss + 2047) / 2048) * 2048
        return ss

    def __str__(self) -> str:
        return f"DiskPartition {{name: {self.name}, size: {self.size_mb}M, offset: {self.offset / 1024 / 1024}M{', path: ' + self.path if self.path else ''}{', fs: ' + self.filesystem if self.filesystem else ''}}}"


RunOutputTypeDefault = Literal["log", "stdout", "interactive", "tui", "null"]
RunOutputTypePopen = Literal["background", "pipe"]
RunOutputType = RunOutputTypeDefault | RunOutputTypePopen
RunReturnType = str | int | subprocess.Popen
PathString = Path | str
Env = dict[str, PathString]
Apkbuild = dict[str, Any]
WithExtraRepos = Literal["default", "enabled", "disabled"]

# These types are not definitive / API, they exist to describe the current
# state of things so that we can improve our type hinting coverage and make
# future refactoring efforts easier.


class PartitionLayout(list[DiskPartition]):
    """
    Subclass list to provide easy accessors without relying on
    fragile indexes while still allowing the partitions to be
    iterated over for simplicity. This is not a good design tbh
    """

    path: str  # path to disk image
    split: bool  # image per partition
    fde: bool

    def __init__(self, path: str, split: bool, fde: bool):
        super().__init__(self)
        # Path to the disk image
        self.path = path
        self.split = split
        self.fde = fde

    @property
    def kernel(self):
        """
        Get the kernel partition (specific to Chromebooks).
        """
        if self[0].name != "kernel":
            raise ValueError("First partition not kernel partition!")
        return self[0]

    @property
    def boot(self):
        """
        Get the boot partition, must be the first or second if we have
        a kernel partition
        """
        if self[0].name == "boot":
            return self[0]
        if self[0].name == "kernel" and self[1].name == "boot":
            return self[1]

        raise ValueError("First partition not boot partition!")

    @property
    def root(self):
        """
        Get the root partition, must be the second or third if we have
        a kernel partition
        """
        if self[1].name == "root":
            return self[1]
        if self[0].name == "kernel" and self[2].name == "root":
            return self[2]

        raise ValueError("First partition not root partition!")


class AportGenEntry(TypedDict):
    prefixes: list[str]
    confirm_overwrite: bool


class Bootimg(TypedDict):
    cmdline: str
    qcdt: str
    qcdt_type: str | None
    dtb_offset: str | None
    dtb_second: str
    base: str
    kernel_offset: str
    ramdisk_offset: str
    second_offset: str
    tags_offset: str
    pagesize: str
    header_version: str | None
    mtk_label_kernel: str
    mtk_label_ramdisk: str


# Property list generated with:
# $ rg --vimgrep "((^|\s)args\.\w+)" --only-matching | cut -d"." -f3 | sort | uniq
class PmbArgs(Namespace):
    action_flasher: str
    action_initfs: str
    action_kconfig: str
    action_netboot: str
    action_test: str
    add: str
    all: bool
    all_git: bool
    all_stable: bool
    android_recovery_zip: bool
    apkindex_path: Path
    aports: list[Path] | None
    arch: Arch | None
    as_root: bool
    assume_yes: bool
    auto: bool
    autoinstall: bool
    boot_size: str
    buildroot: str
    built: bool
    ccache: bool
    ccache_size: str
    chroot_usb: bool
    cipher: str
    clear_log: bool
    cmdline: str
    command: str
    config: Path
    cross: bool
    details: bool
    details_to_stdout: bool
    deviceinfo_parse_kernel: str
    devices: str
    disk: Path
    dry: bool
    efi: bool
    envkernel: bool
    export_folder: Path
    extra_space: str
    fast: bool
    file: str
    filesystem: str
    flash_method: str
    folder: str
    force: bool
    fork_alpine: bool
    fork_alpine_retain_branch: bool
    full_disk_encryption: bool
    go_mod_cache: bool
    hook: str
    host: str
    host_qemu: bool
    http: bool
    ignore_depends: bool
    image_size: str
    install_base: bool
    install_blockdev: bool
    install_cgpt: bool
    install_key: bool
    install_local_pkgs: bool
    install_recommends: bool
    is_default_channel: str
    iter_time: str
    jobs: str
    kconfig_check_details: bool
    kernel: str
    keymap: str
    keep_going: bool
    lines: int
    log: Path
    mirror_alpine: str
    mirror_postmarketos: str
    name: str
    nconfig: bool
    netboot: bool
    no_depends: bool
    no_fde: bool
    no_firewall: bool
    no_image: bool
    no_reboot: bool
    no_sshd: bool
    non_existing: str
    odin_flashable_tar: bool
    offline: bool
    output: RunOutputType
    overview: bool
    # FIXME (#2324): figure out the args.package vs args.packages situation
    package: str | list[str]
    packages: list[str]
    partition: str
    password: str
    path: Path
    pkgname: str
    pkgname_pkgver_srcurl: str
    pkgs_local: bool
    pkgs_local_mismatch: bool
    pkgs_online_mismatch: bool
    port: str
    qemu_audio: str
    qemu_cpu: str
    qemu_display: str
    qemu_gl: bool
    qemu_kvm: bool
    qemu_redir_stdio: str
    qemu_tablet: bool
    qemu_video: str
    recovery_flash_kernel: bool
    recovery_install_partition: str
    ref: str
    replace: bool
    repository: str
    reset: bool
    resume: bool
    rootfs: bool
    rsync: bool
    scripts: str
    second_storage: str
    sector_size: int | None
    selected_providers: dict[str, str]
    sparse: bool
    split: bool
    src: str
    ssh_keys: str
    strict: bool
    suffix: str
    systemd: str
    timeout: float
    user: str
    value: str
    verbose: bool
    verify: bool
    work: Path
    xauth: bool
    xconfig: bool
    zap: bool


# type: ignore
