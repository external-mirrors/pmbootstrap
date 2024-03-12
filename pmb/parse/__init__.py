# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from enum import StrEnum
from pmb.parse.arguments import arguments, arguments_install, arguments_flasher
from pmb.parse._apkbuild import apkbuild
from pmb.parse._apkbuild import function_body
from pmb.parse.binfmt_info import binfmt_info
from pmb.parse.deviceinfo import deviceinfo
from pmb.parse.kconfig import check
from pmb.parse.bootimg import bootimg
from pmb.parse.cpuinfo import arm_big_little_first_group_ncpus
import pmb.parse.arch

class PmbAction(StrEnum):
    INIT = "init"
    CHECKSUM = "checksum"
    CONFIG = "config"
    BOOTIMG_ANALYZE = "bootimg_analyze"
    LOG = "log"
    PULL = "pull"
    SHUTDOWN = "shutdown"
    ZAP = "zap"

# Extracted with `rg --vimgrep "((^|\s)args\.\w+)" --only-matching | cut -d"." -f3 | sort | uniq`
class PmbArgs:
    action: PmbAction
    action_flasher: str
    action_initfs: str
    action_kconfig: str
    action_netboot: str
    add: str
    all: bool
    all_git: str
    all_stable: str
    android_recovery_zip: str
    aports: str
    _aports_real: str
    arch: str
    as_root: str
    assume_yes: str
    auto: str
    autoinstall: str
    boot_size: str
    build_default_device_arch: str
    build_pkgs_on_install: str
    buildroot: str
    built: str
    ccache_size: str
    cipher: str
    clear_log: str
    cmdline: str
    command: str
    config: str
    config_channels: str
    details: str
    details_to_stdout: str
    device: str
    deviceinfo: str
    deviceinfo_parse_kernel: str
    devices: str
    disk: str
    dry: str
    efi: str
    envkernel: str
    export_folder: str
    extra_packages: str
    extra_space: str
    fast: str
    file: str
    filesystem: str
    flash_method: str
    folder: str
    force: str
    fork_alpine: str
    from_argparse: str
    full_disk_encryption: str
    hook: str
    host: str
    hostname: str
    host_qemu: str
    image_size: str
    install_base: str
    install_blockdev: str
    install_cgpt: str
    install_key: str
    install_local_pkgs: str
    install_recommends: str
    is_default_channel: str
    iter_time: str
    jobs: str
    kconfig_check_details: str
    kernel: str
    keymap: str
    lines: str
    log: str
    mirror_alpine: str
    mirrors_postmarketos: str
    name: str
    no_depends: str
    no_fde: str
    no_firewall: str
    no_image: str
    non_existing: str
    no_reboot: str
    no_sshd: str
    odin_flashable_tar: str
    offline: str
    ondev_cp: str
    on_device_installer: str
    ondev_no_rootfs: str
    overview: str
    package: str
    packages: str
    partition: str
    password: str
    path: str
    pkgname: str
    pkgname_pkgver_srcurl: str
    port: str
    qemu_audio: str
    qemu_cpu: str
    qemu_display: str
    qemu_gl: str
    qemu_kvm: str
    qemu_redir_stdio: str
    qemu_tablet: str
    qemu_video: str
    recovery_flash_kernel: str
    recovery_install_partition: str
    ref: str
    replace: str
    repository: str
    reset: str
    resume: str
    rootfs: str
    rsync: str
    scripts: str
    second_storage: str
    selected_providers: str
    sparse: str
    split: str
    src: str
    ssh_keys: str
    strict: str
    sudo_timer: str
    suffix: str
    systemd: str
    timeout: str
    ui: str
    ui_extras: str
    user: str
    value: str
    verbose: str
    verify: str
    work: str
    xauth: str
    zap: str

