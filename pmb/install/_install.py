# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.core.arch import Arch
from pmb.helpers import logging
import os
import re
import glob
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
import shutil

import pmb.build
import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.initfs
import pmb.config
import pmb.config.pmaports
from pmb.helpers.locale import get_xkb_layout
import pmb.parse.depends
from pmb.parse.deviceinfo import Deviceinfo
from pmb.core import Config
from pmb.types import PartitionLayout, PmbArgs, RunOutputTypeDefault
import pmb.helpers.devices
from pmb.helpers.mount import mount_device_rootfs
import pmb.helpers.run
import pmb.helpers.other
import pmb.helpers.package
import pmb.install.blockdevice
import pmb.install.recovery
import pmb.install.ui
import pmb.install
from pmb.core import Chroot, ChrootType
from pmb.core.context import get_context
from pmb.types import DiskPartition

# Keep track of the packages we already visited in get_recommends() to avoid
# infinite recursion
get_recommends_visited: list[str] = []
get_selected_providers_visited: list[str] = []


def get_subpartitions_size(chroot: Chroot) -> tuple[int, int]:
    """
    Calculate the size of the boot and root subpartition.

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    :returns: (boot, root) the size of the boot and root
              partition as integer in bytes
    """
    config = get_context().config
    boot = int(config.boot_size) * 1024 * 1024

    # Estimate root partition size, then add some free space. The size
    # calculation is not as trivial as one may think, and depending on the
    # file system etc it seems to be just impossible to get it right.
    root = pmb.helpers.other.folder_size(chroot.path) * 1024
    root *= 1.20
    root += 50 + int(config.extra_space) * 1024 * 1024
    return (boot, round(root))


def get_nonfree_packages(device: str) -> list[str]:
    """
    Get any legacy non-free subpackages in the APKBUILD.
    Also see: https://postmarketos.org/edge/2024/02/15/default-nonfree-fw/

    :returns: list of non-free packages to be installed. Example:
              ["device-nokia-n900-nonfree-firmware"]
    """
    # Read subpackages
    device_path = pmb.helpers.devices.find_path(device, "APKBUILD")
    if not device_path:
        raise RuntimeError(f"Device package not found for {device}")

    apkbuild = pmb.parse.apkbuild(device_path)
    subpackages = apkbuild["subpackages"]

    # Check for firmware and userland
    ret = []
    prefix = "device-" + device + "-nonfree-"
    if prefix + "firmware" in subpackages:
        ret += [prefix + "firmware"]
    if prefix + "userland" in subpackages:
        ret += [prefix + "userland"]
    return ret


def get_kernel_package(config: Config) -> list[str]:
    """
    Get the device's kernel subpackage based on the user's choice in
    "pmbootstrap init".

    :param device: code name, e.g. "sony-amami"
    :returns: [] or the package in a list, e.g.
              ["device-sony-amami-kernel-mainline"]
    """
    # Empty list: single kernel devices / "none" selected
    kernels = pmb.parse._apkbuild.kernels(config.device)
    if not kernels or config.kernel == "none":
        return []

    # Sanity check
    if config.kernel not in kernels:
        raise RuntimeError(
            "Selected kernel (" + config.kernel + ") is not"
            " valid for device " + config.device + ". Please"
            " run 'pmbootstrap init' to select a valid kernel."
        )

    # Selected kernel subpackage
    return ["device-" + config.device + "-kernel-" + config.kernel]


def copy_files_from_chroot(args: PmbArgs, chroot: Chroot) -> None:
    """
    Copy all files from the rootfs chroot to /mnt/install, except
    for the home folder (because /home will contain some empty
    mountpoint folders).

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    """
    # Mount the device rootfs
    logging.info(f"(native) copy {chroot} to /mnt/install/")
    mountpoint = mount_device_rootfs(chroot)
    mountpoint_outside = Chroot.native() / mountpoint

    # Remove empty qemu-user binary stub (where the binary was bind-mounted)
    arch_qemu = pmb.parse.deviceinfo().arch.qemu_user()
    qemu_binary = mountpoint_outside / f"usr/bin/qemu-{arch_qemu}-static"
    if os.path.exists(qemu_binary):
        pmb.helpers.run.root(["rm", qemu_binary])

    # Remove apk progress fifo
    fifo = chroot / "tmp/apk_progress_fifo"
    if os.path.exists(fifo):
        pmb.helpers.run.root(["rm", fifo])

    # Get all folders inside the device rootfs (except for home)
    folders: list[str] = []
    for path in mountpoint_outside.glob("*"):
        if path.name == "home":
            continue
        folders.append(path.name)

    # Update or copy all files
    if args.rsync:
        pmb.chroot.apk.install(["rsync"], Chroot.native())
        rsync_flags = "-a"
        if args.verbose:
            rsync_flags += "vP"
        pmb.chroot.root(
            ["rsync", rsync_flags, "--delete", *folders, "/mnt/install/"], working_dir=mountpoint
        )
        pmb.chroot.root(["rm", "-rf", "/mnt/install/home"])
    else:
        pmb.chroot.root(["cp", "-a", *folders, "/mnt/install/"], working_dir=mountpoint)

    # Log how much space and inodes we have used
    pmb.chroot.user(["df", "-h", "/mnt/install"])
    pmb.chroot.user(["df", "-i", "/mnt/install"])


def create_home_from_skel(filesystem: str, user: str, rootfs: Path) -> None:
    """
    Create /home/{user} from /etc/skel
    """
    # In btrfs, home subvol & home dir is created in format.py
    if filesystem != "btrfs":
        (rootfs / "home").mkdir(exist_ok=True)

    user_home = rootfs / "home" / user
    if (rootfs / "etc/skel").exists():
        pmb.helpers.run.root(["cp", "-a", (rootfs / "etc/skel"), user_home])
    else:
        user_home.mkdir(exist_ok=True)
    pmb.helpers.run.root(["chown", "-R", "10000:10000", user_home])


def configure_apk(args: PmbArgs, rootfs: Path) -> None:
    """
    Copy over all official keys, and the keys used to compile local packages
    (unless --no-local-pkgs is set). Then copy the corresponding APKINDEX files
    and remove the /cache/packages repository.
    """
    # Official keys
    keys_dir = pmb.config.apk_keys_path

    # Official keys + local keys
    keys_dir = get_context().config.cache / "keys"

    # Copy over keys
    for key in keys_dir.glob("*.pub"):
        shutil.copy(key, rootfs / "etc/apk/keys/")

    # Copy over the corresponding APKINDEX files from cache
    index_files = pmb.helpers.repo.apkindex_files(
        arch=pmb.parse.deviceinfo().arch, user_repository=False
    )

    for f in index_files:
        shutil.copy(f, rootfs / "var/cache/apk/")

    # Populate repositories
    open(rootfs / "etc/apk/repositories", "w").write(
        open(Chroot.native() / "etc/apk/repositories").read()
    )


def set_user(config: Config) -> None:
    """
    Create user with UID 10000 if it doesn't exist.
    Usually the ID for the first user created is 1000, but higher ID is
    chosen here to not cause issues with existing installations. Historically,
    this was done to avoid conflict with Android UIDs/GIDs, but pmOS has since
    dropped support for hybris/Halium.
    """
    chroot = Chroot.rootfs(config.device)
    if not pmb.chroot.user_exists(config.user, chroot):
        pmb.chroot.root(["adduser", "-D", "-u", "10000", config.user], chroot)

    pmaports_cfg = pmb.config.pmaports.read_config()
    groups = []
    groups += pmaports_cfg.get(
        "install_user_groups", "audio,input,netdev,plugdev,video,wheel"
    ).split(",")
    groups += pmb.install.ui.get_groups(config)

    for group in groups:
        # Create system group
        pmb.chroot.rootm(
            [["addgroup", "-S", group], ["addgroup", config.user, group]], chroot, check=False
        )
        # Add user to the group
        pmb.chroot.root(["addgroup", config.user, group], chroot)


def setup_login_chpasswd_user_from_arg(args: PmbArgs, user: str, chroot: Chroot) -> None:
    """
    Set the user's password from what the user passed as --password. Make an
    effort to not have the password end up in the log file by writing it to
    a temp file, instead of "echo user:$pass | chpasswd". The user should of
    course only use this with a test password anyway, but let's be nice and try
    to have the user protected from accidentally posting their password in
    any case.

    :param suffix: of the chroot, where passwd will be execute (either the
                   rootfs_{args.device} or installer_{args.device}
    """
    path = "/tmp/pmbootstrap_chpasswd_in"
    path_outside = chroot / path

    with open(path_outside, "w", encoding="utf-8") as handle:
        handle.write(f"{user}:{args.password}")

    pmb.chroot.root(["sh", "-c", f"cat {shlex.quote(path)} | chpasswd"], chroot)

    os.unlink(path_outside)


def is_root_locked(chroot: Chroot) -> bool:
    """
    Figure out from /etc/shadow if root is already locked. The output of this
    is stored in the log, so use grep to only log the line for root, not the
    line for the user which contains a hash of the user's password.

    :param suffix: either rootfs_{args.device} or installer_{args.device}
    """
    shadow_root = pmb.chroot.root(
        ["grep", "^root:!:", "/etc/shadow"], chroot, output_return=True, check=False
    )
    return shadow_root.startswith("root:!:")


def setup_login(args: PmbArgs, config: Config, chroot: Chroot) -> None:
    """
    Loop until the password for user has been set successfully, and disable
    root login.

    :param suffix: of the chroot, where passwd will be execute (either the
                   rootfs_{args.device} or installer_{args.device}
    """
    # User password
    logging.info(f" *** SET LOGIN PASSWORD FOR: '{config.user}' ***")
    if args.password:
        setup_login_chpasswd_user_from_arg(args, config.user, chroot)
    else:
        while True:
            try:
                pmb.chroot.root(["passwd", config.user], chroot, output=RunOutputTypeDefault.INTERACTIVE)
                break
            except RuntimeError:
                logging.info("WARNING: Failed to set the password. Try it one more time.")

    # Disable root login
    if is_root_locked(chroot):
        logging.debug(f"({chroot}) root is already locked")
    else:
        logging.debug(f"({chroot}) locking root")
        pmb.chroot.root(["passwd", "-l", "root"], chroot)


def copy_ssh_keys(config: Config, rootfs: Path) -> None:
    """
    If requested, copy user's SSH public keys to the device if they exist
    """
    if not config.ssh_keys:
        return
    keys = []
    for key in glob.glob(os.path.expanduser(config.ssh_key_glob)):
        with open(key) as infile:
            try:
                keys += infile.readlines()
            except UnicodeDecodeError:
                logging.info(
                    f"WARNING: {key} is not a valid SSH key. "
                    "This file will not be copied to device."
                )

    if not len(keys):
        logging.info(
            "NOTE: Public SSH keys not found. Since no SSH keys "
            "were copied, you will need to use SSH password "
            "authentication!"
        )
        return

    authorized_keys = Chroot.native() / "tmp/authorized_keys"
    with open(authorized_keys, "w") as outfile:
        for key in keys:
            outfile.write(f"{key}")

    target = rootfs / "home/" / config.user / ".ssh"
    target.mkdir(exist_ok=True)
    pmb.helpers.run.root(["chmod", "700", target])
    pmb.helpers.run.root(["cp", authorized_keys, target / "authorized_keys"])
    pmb.helpers.run.root(["rm", authorized_keys])
    pmb.helpers.run.root(["chown", "-R", "10000:10000", target])


def setup_keymap(config: Config, chroot: Chroot) -> None:
    """
    Set the keymap with the setup-keymap utility if the device requires it
    """
    deviceinfo = pmb.parse.deviceinfo(device=config.device)
    if not deviceinfo.keymaps or deviceinfo.keymaps.strip() == "":
        logging.info("NOTE: No valid keymap specified for device")
        return
    options = deviceinfo.keymaps.split(" ")
    if config.keymap != "" and config.keymap is not None and config.keymap in options:
        layout, variant = config.keymap.split("/")
        pmb.chroot.root(
            ["setup-keymap", layout, variant], chroot, output=RunOutputTypeDefault.INTERACTIVE
        )

        # Check xorg config
        xconfig = None
        if (chroot / "etc/X11/xorg.conf.d").exists():
            xconfig = pmb.chroot.root(
                ["grep", "-rl", "XkbLayout", "/etc/X11/xorg.conf.d/"],
                chroot,
                check=False,
                output_return=True,
            )
        if xconfig:
            # Nokia n900 (RX-51) randomly merges some keymaps so we
            # have to specify a composite keymap for a few countries. See:
            # https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/master/symbols/nokia_vndr/rx-51
            if variant == "rx51_fi" or variant == "rx51_se":
                layout = "fise"
            if variant == "rx51_da" or variant == "rx51_no":
                layout = "dano"
            if variant == "rx51_pt" or variant == "rx51_es":
                layout = "ptes"
            # Multiple files can contain the keyboard layout, take last
            xconfig = xconfig.splitlines()[-1]
            old_text = 'Option *\\"XkbLayout\\" *\\".*\\"'
            new_text = 'Option \\"XkbLayout\\" \\"' + layout + '\\"'
            pmb.chroot.root(["sed", "-i", "s/" + old_text + "/" + new_text + "/", xconfig], chroot)
    else:
        logging.info("NOTE: No valid keymap specified for device")


def setup_timezone(chroot: Chroot, timezone: str) -> None:
    # We don't care about the arch since it's built for all!
    alpine_conf = pmb.helpers.package.get("alpine-conf", Arch.native())
    version = alpine_conf.version.split("-r")[0]

    setup_tz_cmd = ["setup-timezone"]
    # setup-timezone will, by default, copy the timezone to /etc/zoneinfo
    # and disregard tzdata, to save space. If we actually have tzdata
    # installed, make sure that setup-timezone makes use of it, since
    # there's no space to be saved.
    if "tzdata" in pmb.chroot.apk.installed(chroot):
        setup_tz_cmd += ["-i"]
    if not pmb.parse.version.check_string(version, ">=3.14.0"):
        setup_tz_cmd += ["-z"]
    setup_tz_cmd += [timezone]
    pmb.chroot.root(setup_tz_cmd, chroot)


def setup_locale(chroot: Chroot, locale: str) -> None:
    """
    Set locale-related settings such as $LANG and keyboard layout
    """
    # 10locale-pmos.sh gets sourced before 20locale.sh from
    # alpine-baselayout by /etc/profile. Since they don't override the
    # locale if it exists, it warranties we have preference
    pmb.chroot.root(["sh", "-c", f"echo LANG={shlex.quote(locale)} > /etc/locale.conf"], chroot)
    # musl-locales doesn't read from /etc/locale.conf, only from environment variables
    # TODO: once musl implements locales (hopefully with /etc/locale.conf support) the following should be removed
    pmb.chroot.root(
        ["sh", "-c", "echo source /etc/locale.conf > /etc/profile.d/10locale-pmos.sh"], chroot
    )
    # add keyboard layout related to locale and layout switcher
    xkb_layout = get_xkb_layout(locale)
    xkb_vars = xkb_layout.get_profile_vars()
    if xkb_vars:
        xkb_vars = xkb_vars.replace("\n", "\\n")
        pmb.chroot.root(
            ["sed", "-i", "$a\\" + xkb_vars, "/etc/profile.d/10locale-pmos.sh"],
            chroot,
        )
    if (chroot / "etc/X11").exists() and (kb_config := xkb_layout.get_keyboard_config()):
        config_name = "99-keyboard.conf"
        config_tmp_path = f"/tmp/{config_name}"
        config_path = f"/etc/X11/xorg.conf.d/{config_name}"
        pmb.chroot.root(["mkdir", "-p", "/etc/X11/xorg.conf.d"], chroot)
        with open(chroot / config_tmp_path, "w") as f:
            f.write(kb_config)
        pmb.chroot.root(["mv", config_tmp_path, config_path], chroot)
        pmb.chroot.root(["chown", "root:root", config_path], chroot)


def setup_hostname(device: str, hostname: str | None) -> None:
    """
    Set the hostname and update localhost address in /etc/hosts
    """
    # Default to device name. If device name is not a valid hostname then
    # default to a static default.
    if not hostname:
        hostname = pmb.helpers.other.normalize_hostname(device)
        if not pmb.helpers.other.validate_hostname(hostname):
            # A valid host name, see:
            # https://datatracker.ietf.org/doc/html/rfc1035#section-2.3.1
            hostname = "postmarketos-device"
    elif not pmb.helpers.other.validate_hostname(hostname):
        # Invalid hostname set by the user e.g., via pmb init, this should
        # fail so they can fix it
        raise RuntimeError(
            "Hostname '" + hostname + "' is not valid, please"
            " run 'pmbootstrap init' to configure it."
        )

    suffix = Chroot(ChrootType.ROOTFS, device)
    # Generate /etc/hostname
    pmb.chroot.root(["sh", "-c", "echo " + shlex.quote(hostname) + " > /etc/hostname"], suffix)
    # Update /etc/hosts
    regex = (
        r"s/^127\.0\.0\.1.*/127.0.0.1\t" + re.escape(hostname) + " localhost.localdomain localhost/"
    )
    pmb.chroot.root(["sed", "-i", "-e", regex, "/etc/hosts"], suffix)


def setup_appstream(offline: bool, chroot: Chroot) -> None:
    """
    If alpine-appstream-downloader has been downloaded, execute it to have
    update AppStream data on new installs
    """
    installed_pkgs = pmb.chroot.apk.installed(chroot)

    if "alpine-appstream-downloader" not in installed_pkgs or offline:
        return

    target_dir = Path("/cache/appstream") / chroot.arch / chroot.channel
    logging.info(f"appstream target dir: {target_dir}")

    # FIXME: it would be great to run this on the host and not potentially
    # through QEMU!
    if not pmb.chroot.root(["alpine-appstream-downloader", target_dir], chroot, check=False):
        pmb.chroot.root(["mkdir", "-p", "/var/lib/swcatalog"], chroot)
        pmb.chroot.root(
            [
                "cp",
                "-r",
                target_dir / "icons",
                target_dir / "xml",
                "-t",
                "/var/lib/swcatalog",
            ],
            chroot,
        )


def print_sshd_info(args: PmbArgs) -> None:
    logging.info("")  # make the note stand out
    logging.info("*** SSH DAEMON INFORMATION ***")

    if args.no_sshd:
        logging.info("SSH daemon is disabled (--no-sshd).")
    else:
        logging.info("SSH daemon is enabled (disable with --no-sshd).")
        logging.info(
            f"Login as '{get_context().config.user}' with the password given during installation."
        )


def disable_service_systemd(chroot: Chroot, service_name: str) -> None:
    preset = f"/usr/lib/systemd/system-preset/80-pmbootstrap-install-disable-{service_name}.preset"
    preset_content = f"disable {service_name}.service"
    pmb.chroot.root(
        ["sh", "-c", f"echo {shlex.quote(preset_content)} > {shlex.quote(preset)}"], chroot
    )
    pmb.chroot.root(["systemctl", "preset", f"{service_name}.service"], chroot)

    # Use the output instead of exit code to be more explicit and so we can put
    # it in the error message
    output = pmb.chroot.root(
        ["systemctl", "is-enabled", f"{service_name}.service"],
        chroot,
        output_return=True,
        check=False,
    )
    output = output.rstrip()
    if output != "disabled":
        raise RuntimeError(f"Failed to disable {service_name} service (systemd preset): {output}")


def disable_service_openrc(chroot: Chroot, service_name: str) -> None:
    # check=False: rc-update doesn't exit with 0 if already disabled
    pmb.chroot.root(["rc-update", "del", service_name, "default"], chroot, check=False)

    # Verify that it's gone
    runlevel_files = pmb.helpers.run.root(
        ["find", "-name", service_name], output_return=True, working_dir=chroot / "etc/runlevels"
    )
    if runlevel_files:
        raise RuntimeError(f"Failed to disable service {service_name} (openrc): {runlevel_files}")


def disable_service(chroot: Chroot, service_name: str) -> None:
    if pmb.config.is_systemd_selected():
        disable_service_systemd(chroot, service_name)
    else:
        disable_service_openrc(chroot, service_name)


def print_firewall_info(disabled: bool, arch: Arch) -> None:
    pmaports_cfg = pmb.config.pmaports.read_config()
    pmaports_ok = pmaports_cfg.get("supported_firewall", None) == "nftables"

    # Find kernel pmaport (will not be found if Alpine kernel is used)
    apkbuild_found = False
    apkbuild_has_opt = False

    kernel = get_kernel_package(get_context().config)
    if kernel:
        _, kernel_apkbuild = pmb.build.get_apkbuild(kernel[0])
        if kernel_apkbuild:
            opts = kernel_apkbuild["options"]
            apkbuild_has_opt = "pmb:kconfigcheck-nftables" in opts
            apkbuild_found = True

    # Print the note and make it stand out
    logging.info("")
    logging.info("*** FIREWALL INFORMATION ***")

    if not pmaports_ok:
        logging.info("Firewall is not supported in checked out pmaports branch.")
    elif disabled:
        logging.info("Firewall is disabled (--no-firewall).")
    elif not apkbuild_found:
        logging.info(
            "Firewall is enabled, but may not work (couldn't"
            " determine if kernel supports nftables)."
        )
    elif apkbuild_has_opt:
        logging.info("Firewall is enabled and supported by kernel.")
    else:
        logging.info(
            "Firewall is enabled, but will not work (no support in kernel config for nftables)."
        )
        logging.info("If/when the kernel supports it in the future, it will work automatically.")

    logging.info("For more information: https://postmarketos.org/firewall")


def generate_binary_list(args: PmbArgs, chroot: Chroot, step: int) -> list[tuple[str, int]]:
    """
    Perform three checks prior to writing binaries to disk: 1) that binaries
    exist, 2) that binaries do not extend into the first partition, 3) that
    binaries do not overlap each other.

    :param suffix: of the chroot, which holds the firmware files (either the
                   rootfs_{args.device} or installer_{args.device}
    :param step: partition step size in bytes
    """
    binary_ranges: dict[int, int] = {}
    binary_list = []
    binaries = (pmb.parse.deviceinfo().sd_embed_firmware or "").split(",")

    for binary_offset in binaries:
        binary, offset_ = binary_offset.split(":")
        try:
            offset = int(offset_)
        except ValueError:
            raise RuntimeError(f"Value for firmware binary offset is not valid: {offset}")
        binary_path = chroot / "usr/share" / binary
        if not os.path.exists(binary_path):
            raise RuntimeError(
                "The following firmware binary does not "
                f"exist in the {chroot} chroot: "
                f"/usr/share/{binary}"
            )
        # Insure that embedding the firmware will not overrun the
        # first partition
        boot_part_start = pmb.parse.deviceinfo().boot_part_start
        max_size = (boot_part_start * pmb.config.block_size) - (offset * step)
        binary_size = os.path.getsize(binary_path)
        if binary_size > max_size:
            raise RuntimeError(
                f"The firmware is too big to embed in the disk image {binary_size}B > {max_size}B"
            )
        # Insure that the firmware does not conflict with any other firmware
        # that will be embedded
        binary_start = offset * step
        binary_end = binary_start + binary_size
        for start, end in binary_ranges.items():
            if (binary_start >= start and binary_start < end) or (
                binary_end > start and binary_end <= end
            ):
                raise RuntimeError(
                    f"The firmware overlaps with at least one other firmware image: {binary}"
                )

        binary_ranges[binary_start] = binary_end
        binary_list.append((binary, offset))

    return binary_list


def embed_firmware(args: PmbArgs, suffix: Chroot) -> None:
    """
    This method will embed firmware, located at /usr/share, that are specified
    by the "sd_embed_firmware" deviceinfo parameter into the SD card image
    (e.g. u-boot). Binaries that would overwrite the first partition are not
    accepted, and if multiple binaries are specified then they will be checked
    for collisions with each other.

    :param suffix: of the chroot, which holds the firmware files (either the
                   rootfs_{args.device} or installer_{args.device}
    """
    if not pmb.parse.deviceinfo().sd_embed_firmware:
        return

    step = 1024
    if pmb.parse.deviceinfo().sd_embed_firmware_step_size:
        try:
            step = int(pmb.parse.deviceinfo().sd_embed_firmware_step_size or "invalid")
        except ValueError:
            raise RuntimeError(
                f"Value for deviceinfo_sd_embed_firmware_step_size is not valid: {step}"
            )

    device_rootfs = mount_device_rootfs(suffix)
    binary_list = generate_binary_list(args, suffix, step)

    # Write binaries to disk
    for binary, offset in binary_list:
        binary_file = os.path.join("/usr/share", binary)
        logging.info(
            f"Embed firmware {binary} in the SD card image at offset {offset} with step size {step}"
        )
        filename = os.path.join(device_rootfs, binary_file.lstrip("/"))
        pmb.chroot.root(
            ["dd", "if=" + filename, "of=/dev/install", "bs=" + str(step), "seek=" + str(offset)]
        )


def write_cgpt_kpart(args: PmbArgs, layout: PartitionLayout, suffix: Chroot) -> None:
    """
    Write the kernel to the ChromeOS kernel partition.

    :param layout: partition layout from get_partition_layout()
    :param suffix: of the chroot, which holds the image file to be flashed
    """
    if not pmb.parse.deviceinfo().cgpt_kpart or not args.install_cgpt:
        return

    device_rootfs = mount_device_rootfs(suffix)
    filename = f"{device_rootfs}{pmb.parse.deviceinfo().cgpt_kpart}"
    pmb.chroot.root(["dd", f"if={filename}", f"of=/dev/installp{layout['kernel']}"])


def sanity_check_boot_size() -> None:
    default = Config().boot_size
    config = get_context().config
    if int(config.boot_size) >= int(default):
        return
    logging.error(
        "ERROR: your pmbootstrap has a small/invalid boot_size of"
        f" {config.boot_size} configured, probably because the config"
        " has been created with an old version."
    )
    logging.error(f"This can lead to problems later on, we recommend setting it to {default} MiB.")
    logging.error(f"Run 'pmbootstrap config boot_size {default}' and try again.")
    sys.exit(1)


def sanity_check_disk(args: PmbArgs) -> None:
    device = args.disk
    device_name = os.path.basename(device)
    if not os.path.exists(device):
        raise RuntimeError(f"{device} doesn't exist, is the disk plugged?")
    if os.path.isdir(f"/sys/class/block/{device_name}"):
        with open(f"/sys/class/block/{device_name}/ro") as handle:
            ro = handle.read()
        if ro == "1\n":
            raise RuntimeError(f"{device} is read-only, maybe a locked SD card?")


def sanity_check_disk_size(args: PmbArgs) -> None:
    device = args.disk
    devpath = os.path.realpath(device)
    sysfs = "/sys/class/block/{}/size".format(devpath.replace("/dev/", ""))
    if not os.path.isfile(sysfs):
        # This is a best-effort sanity check, continue if it's not checkable
        return

    with open(sysfs) as handle:
        raw = handle.read()

    # Size is in 512-byte blocks some of the time...
    size = int(raw.strip())
    human = f"{size / 2 / 1024 / 1024:.2f} GiB"

    # Warn if the size is larger than 100GiB
    if (
        not args.assume_yes
        and size > (100 * 2 * 1024 * 1024)
        and not pmb.helpers.cli.confirm(
            f"WARNING: The target disk ({devpath}) "
            "is larger than a usual SD card "
            "(>100GiB). Are you sure you want to "
            f"overwrite this {human} disk?",
            no_assumptions=True,
        )
    ):
        raise RuntimeError("Aborted.")


def get_partition_layout(
    chroot: Chroot, kernel: bool, split: bool, single_partition: bool, fde: bool
) -> PartitionLayout:
    """
    :param kernel: create a separate kernel partition before all other
                   partitions, e.g. for the ChromeOS devices with cgpt
    :returns: the partition layout, e.g. without reserve and kernel:
              {"kernel": None, "boot": 1, "reserve": None, "root": 2}
    """
    layout: PartitionLayout = PartitionLayout("/dev/install", split, fde)

    if kernel:
        layout.append(DiskPartition("kernel", pmb.parse.deviceinfo().cgpt_kpart_size))

    (size_boot, size_root) = get_subpartitions_size(chroot)

    if single_partition:
        if kernel:
            # FIXME: check this way earlier!
            raise RuntimeError("--single-partition is not supported on Chromebooks, sorry!")
        layout.append(DiskPartition("root", size_root))
        return layout

    layout.append(DiskPartition("boot", size_boot))
    layout.append(DiskPartition("root", size_root))

    if split:
        layout.boot.path = "/dev/installp1"
        layout.root.path = "/dev/installp2"
    else:
        # Both partitions are in the same disk image and we access
        # them with offsets
        layout.boot.path = "/dev/install"
        layout.root.path = "/dev/install"

    return layout


def get_uuid(args: PmbArgs, disk: Path, partition: str) -> str:
    pass


def create_crypttab(args: PmbArgs, layout: PartitionLayout, disk: Path, chroot: Chroot) -> None:
    """
    Create /etc/crypttab config

    :param layout: partition layout from get_partition_layout() or None
    :param suffix: of the chroot, which crypttab will be created to
    """

    luks_uuid = layout.root.uuid
    crypttab = f"root UUID={luks_uuid} none luks\n"

    (chroot / "tmp/crypttab").open("w").write(crypttab)
    pmb.chroot.root(["mv", "/tmp/crypttab", "/etc/crypttab"], chroot)


def create_fstab(args: PmbArgs, layout: PartitionLayout, disk: Path, chroot: Chroot) -> None:
    """
    Create /etc/fstab config

    :param layout: partition layout from get_partition_layout() or None
    :param chroot: of the chroot, which fstab will be created to
    """

    root_mount_point = (
        "/dev/mapper/root" if args.full_disk_encryption else f"UUID={layout.root.uuid}"
    )
    root_filesystem = pmb.install.get_root_filesystem(args)

    if root_filesystem == "btrfs":
        # btrfs gets separate subvolumes for root, var and home
        fstab = f"""
# <file system> <mount point> <type> <options> <dump> <pass>
{root_mount_point} / btrfs subvol=@,compress=zstd:2,ssd 0 0
{root_mount_point} /home btrfs subvol=@home,compress=zstd:2,ssd 0 0
{root_mount_point} /root btrfs subvol=@root,compress=zstd:2,ssd 0 0
{root_mount_point} /srv btrfs subvol=@srv,compress=zstd:2,ssd 0 0
{root_mount_point} /var btrfs subvol=@var,ssd 0 0
{root_mount_point} /.snapshots btrfs subvol=@snapshots,compress=zstd:2,ssd 0 0
""".lstrip()

    else:
        fstab = f"""
# <file system> <mount point> <type> <options> <dump> <pass>
{root_mount_point} / {root_filesystem} defaults 0 0
""".lstrip()

    # FIXME: need a better way to check if we have a boot partition...
    if len(layout) > 1:
        boot_mount_point = f"UUID={layout.boot.uuid}"
        boot_options = "nodev,nosuid,noexec"
        boot_filesystem = pmb.parse.deviceinfo().boot_filesystem or "ext2"
        if boot_filesystem in ("fat16", "fat32"):
            boot_filesystem = "vfat"
            boot_options += ",umask=0077,nosymfollow,codepage=437,iocharset=ascii"
        fstab += f"{boot_mount_point} /boot {boot_filesystem} {boot_options} 0 0\n"

    with (chroot / "tmp/fstab").open("w") as f:
        f.write(fstab)
    print(fstab)
    pmb.chroot.root(["mv", "/tmp/fstab", "/etc/fstab"], chroot)


def get_root_filesystem(args: PmbArgs) -> str:
    ret = args.filesystem or pmb.parse.deviceinfo().root_filesystem or "ext4"
    pmaports_cfg = pmb.config.pmaports.read_config()

    supported = pmaports_cfg.get("supported_root_filesystems", "ext4")
    supported_list = supported.split(",")

    if ret not in supported_list:
        raise ValueError(
            f"Root filesystem {ret} is not supported by your"
            " currently checked out pmaports branch. Update your"
            " branch ('pmbootstrap pull'), change it"
            " ('pmbootstrap init'), or select one of these"
            f" filesystems: {', '.join(supported_list)}"
        )
    return ret


def install_system_image(
    args: PmbArgs,
    chroot: Chroot,
    step: int,
    steps: int,
    split: bool = False,
    single_partition: bool = False,
    disk: Path | None = None,
) -> None:
    """
    :param suffix: the chroot suffix, where the rootfs that will be installed
                   on the device has been created (e.g. "rootfs_qemu-amd64")
    :param step: next installation step
    :param steps: total installation steps
    :param boot_label: label of the boot partition (e.g. "pmOS_boot")
    :param root_label: label of the root partition (e.g. "pmOS_root")
    :param split: create separate images for boot and root partitions
    :param disk: path to disk block device (e.g. /dev/mmcblk0) or None
    """
    config = get_context().config
    device = chroot.name
    deviceinfo = pmb.parse.deviceinfo()
    # Partition and fill image file/disk block device
    logging.info(f"*** ({step}/{steps}) PREPARE INSTALL BLOCKDEVICE ***")
    pmb.chroot.umount(chroot)
    layout = get_partition_layout(
        chroot,
        bool(deviceinfo.cgpt_kpart and args.install_cgpt),
        split,
        single_partition,
        args.full_disk_encryption,
    )
    logging.info(f"split: {split}")
    logging.info("Using partition layout:")
    logging.info(", ".join([str(x) for x in layout]))
    if not args.rsync:
        pmb.install.blockdevice.create(args, layout, split, disk)
        if not split and not single_partition:
            if deviceinfo.cgpt_kpart and args.install_cgpt:
                pmb.install.partition_cgpt(layout)
            else:
                pmb.install.partition(layout)
        else:
            layout.root.offset = 0
            if not single_partition:
                layout.boot.offset = 0

    # if not split and not single_partition:
    #     assert layout  # Initialized above for not single_partition case (mypy needs this)
    #     pmb.install.partitions_mount(device, layout, disk)

    layout.root.filesystem = get_root_filesystem(args)
    layout.boot.filesystem = deviceinfo.boot_filesystem or "ext2"

    # Since we shut down the chroot we need to mount it again
    pmb.chroot.mount(chroot)

    # Create /etc/fstab and /etc/crypttab
    logging.info("(native) create /etc/fstab")
    # FIXME: don't hardcode /dev/install everywhere!
    create_fstab(args, layout, "/dev/install", chroot)
    if args.full_disk_encryption:
        logging.info("(native) create /etc/crypttab")
        create_crypttab(args, layout, "/dev/install", chroot)

    # Run mkinitfs to pass UUIDs to cmdline
    logging.info(f"({chroot}) mkinitfs")
    pmb.chroot.root(["mkinitfs"], chroot)

    # Clean up after running mkinitfs in chroot
    pmb.chroot.umount(chroot)
    (chroot / "in-pmbootstrap").unlink(missing_ok=True)
    pmb.chroot.remove_mnt_pmbootstrap(chroot)

    # Just copy all the files
    logging.info(f"*** ({step + 1}/{steps}) FORMAT AND COPY BLOCKDEVICE ***")
    create_home_from_skel(args.filesystem, config.user, chroot.path)
    configure_apk(args, chroot.path)
    copy_ssh_keys(config, chroot.path)

    # The formatting step also copies files into the disk image
    pmb.install.format(args, layout, chroot.path, disk)

    # Don't try to embed firmware and cgpt on split images since there's no
    # place to put it and it will end up in /dev of the chroot instead
    if not split and not single_partition:
        assert layout  # Initialized above for not single_partition case (mypy needs this)
        embed_firmware(args, chroot)
        write_cgpt_kpart(args, layout, chroot)

    if disk:
        logging.info(f"Unmounting disk {disk} (this may take a while to sync, please wait)")
    pmb.chroot.shutdown(True)

    # Convert rootfs to sparse using img2simg
    sparse = args.sparse
    if sparse is None:
        sparse = deviceinfo.flash_sparse == "true"

    if sparse and not split and not disk:
        workdir = Path("/home/pmos/rootfs")
        logging.info("(native) make sparse rootfs")
        pmb.chroot.apk.install(["android-tools"], Chroot.native())
        sys_image = device + ".img"
        sys_image_sparse = device + "-sparse.img"
        pmb.chroot.user(["img2simg", sys_image, sys_image_sparse], working_dir=workdir)
        pmb.chroot.user(["mv", "-f", sys_image_sparse, sys_image], working_dir=workdir)

        # patch sparse image for Samsung devices if specified
        samsungify_strategy = deviceinfo.flash_sparse_samsung_format
        if samsungify_strategy:
            logging.info("(native) convert sparse image into Samsung's sparse image format")
            pmb.chroot.apk.install(["sm-sparse-image-tool"], Chroot.native())
            sys_image = f"{device}.img"
            sys_image_patched = f"{device}-patched.img"
            pmb.chroot.user(
                [
                    "sm_sparse_image_tool",
                    "samsungify",
                    "--strategy",
                    samsungify_strategy,
                    sys_image,
                    sys_image_patched,
                ],
                working_dir=workdir,
            )
            pmb.chroot.user(["mv", "-f", sys_image_patched, sys_image], working_dir=workdir)


def print_flash_info(
    device: str, deviceinfo: Deviceinfo, split: bool, have_disk: bool, single_partition: bool
) -> None:
    """Print flashing information, based on the deviceinfo data and the
    pmbootstrap arguments."""
    logging.info("")  # make the note stand out
    logging.info("*** FLASHING INFORMATION ***")

    # System flash information
    method = deviceinfo.flash_method
    flasher = pmb.config.flashers.get(method, {})
    flasher_actions = flasher.get("actions", {})
    if not isinstance(flasher_actions, dict):
        raise TypeError(f"flasher actions must be a dictionary, got: {flasher_actions}")
    requires_split = flasher.get("split", False)

    if method == "none":
        logging.info(
            "Refer to the installation instructions of your device,"
            " or the generic install instructions in the wiki."
        )
        logging.info("https://wiki.postmarketos.org/wiki/Installation_guide#pmbootstrap_flash")
        return

    logging.info("Run the following to flash your installation to the target device:")

    if "flash_rootfs" in flasher_actions and not have_disk and bool(split) == requires_split:
        logging.info("* pmbootstrap flasher flash_rootfs")
        logging.info("  Flashes the generated rootfs image to your device:")
        if split:
            logging.info(f"  {Chroot.native() / 'home/pmos/rootfs' / device}-root.img")
        else:
            logging.info(f"  {Chroot.native() / 'home/pmos/rootfs' / device}.img")
            if not single_partition:
                logging.info(
                    "  (NOTE: This file has a partition table, which"
                    " contains /boot and / subpartitions. That way we"
                    " don't need to change the partition layout on your"
                    " device.)"
                )

    # if current flasher supports vbmeta and partition is explicitly specified
    # in deviceinfo
    if "flash_vbmeta" in flasher_actions and (
        deviceinfo.flash_fastboot_partition_vbmeta or deviceinfo.flash_heimdall_partition_vbmeta
    ):
        logging.info("* pmbootstrap flasher flash_vbmeta")
        logging.info("  Flashes vbmeta image with verification disabled flag.")

    # if current flasher supports dtbo and partition is explicitly specified
    # in deviceinfo
    if "flash_dtbo" in flasher_actions and (
        deviceinfo.flash_fastboot_partition_dtbo or deviceinfo.flash_heimdall_partition_dtbo
    ):
        logging.info("* pmbootstrap flasher flash_dtbo")
        logging.info("  Flashes dtbo image.")

    # Most flash methods operate independently of the boot partition.
    # (e.g. an Android boot image is generated). In that case, "flash_kernel"
    # works even when partitions are split or installing to disk. This is not
    # possible if the flash method requires split partitions.
    if "flash_kernel" in flasher_actions and (not requires_split or split):
        logging.info("* pmbootstrap flasher flash_kernel")
        logging.info("  Flashes the kernel + initramfs to your device:")
        if requires_split:
            logging.info(f"  {Chroot.native() / 'home/pmos/rootfs' / device}-boot.img")
        else:
            logging.info(f"  {Chroot(ChrootType.ROOTFS, device) / 'boot'}")

    if "flash_boot" in flasher_actions and (Chroot.rootfs(device) / "boot/boot.img").exists():
        logging.info("* pmbootstrap flasher flash_boot")
        logging.info("  Flashes the generated Android boot image to your device:")
        logging.info(f"  {Chroot.rootfs(device) / 'boot/boot.img'}")
        logging.info("  (NOTE: This is not necessary if using a custom bootloader like U-Boot)")

    if "boot" in flasher_actions or "boot_gki" in flasher_actions:
        logging.info(
            "  (NOTE: " + method + " also supports booting"
            " the kernel/initramfs directly without flashing."
            " Use 'pmbootstrap flasher boot' to do that.)"
        )

    if (
        "flash_lk2nd" in flasher_actions
        and (Chroot(ChrootType.ROOTFS, device) / "boot/lk2nd.img").exists()
    ):
        logging.info(
            "* Your device supports and may even require"
            " flashing lk2nd. You should flash it before"
            " flashing anything else. Use 'pmbootstrap flasher"
            " flash_lk2nd' to do that."
        )

    # Export information
    logging.info(
        "* If the above steps do not work, you can also create"
        " symlinks to the generated files with 'pmbootstrap export'"
        " and flash outside of pmbootstrap."
    )


def install_recovery_zip(args: PmbArgs, device: str, arch: Arch, steps: int) -> None:
    logging.info(f"*** ({steps}/{steps}) CREATING RECOVERY-FLASHABLE ZIP ***")
    chroot = Chroot(ChrootType.BUILDROOT, arch)
    pmb.chroot.init(chroot)
    mount_device_rootfs(Chroot.rootfs(device), chroot)
    pmb.install.recovery.create_zip(args, chroot, device)

    # Flash information
    logging.info("*** FLASHING INFORMATION ***")
    logging.info("Flashing with the recovery zip is explained here:")
    logging.info("https://postmarketos.org/recoveryzip")


def get_selected_providers(args: PmbArgs, packages: list[str]) -> list[str]:
    """
    Look through the specified packages and see which providers were selected
    in "pmbootstrap init". Install those as extra packages to select them
    instead of the default provider. This function is called recursively on the
    dependencies of the given packages.

    :param packages: the packages that have selectable providers (_pmb_select)
    :param initial: used internally when the function calls itself
    :return: additional provider packages to install
    """
    global get_selected_providers_visited

    ret = []

    for package in packages:
        if package in get_selected_providers_visited:
            logging.verbose(f"get_selected_providers: {package}: already visited")
            continue
        get_selected_providers_visited += [package]

        # Note that this ignores packages that don't exist. This means they
        # aren't in pmaports. This is fine, with the assumption that
        # installation will fail later in some other method if they truly don't
        # exist in any repo.
        apkbuild = pmb.helpers.pmaports.get(package, subpackages=False, must_exist=False)
        if not apkbuild:
            continue
        for select in apkbuild["_pmb_select"]:
            if select in get_context().config.providers:
                ret += [get_context().config.providers[select]]
                logging.verbose(f"{package}: install selected_providers: {', '.join(ret)}")
            else:
                for default in apkbuild["_pmb_default"]:
                    # default: e.g. "postmarketos-base-ui-audio-pipewire"
                    # select: e.g. "postmarketos-base-ui-audio"
                    if default.startswith(f"{select}-"):
                        ret += [default]
        # Also iterate through dependencies to collect any providers they have
        depends = apkbuild["depends"]
        if depends:
            ret += get_selected_providers(args, depends)

    return ret


def get_recommends(args: PmbArgs, packages: list[str]) -> Sequence[str]:
    """
    Look through the specified packages and collect additional packages
    specified under _pmb_recommends in them. This is recursive, so it will dive
    into packages that are listed under recommends to collect any packages they
    might also have listed under their own _pmb_recommends.

    Recursion is only done into packages found in pmaports.

    If running with pmbootstrap install --no-recommends, this function returns
    an empty list.

    :param packages: list of packages of which we want to get the recommends
    :param initial: used internally when the function calls itself
    :returns: list of pkgnames, e.g. ["chatty", "gnome-contacts"]
    """
    global get_recommends_visited

    ret: list[str] = []
    if not args.install_recommends:
        return ret

    for package in packages:
        if package in get_recommends_visited:
            logging.verbose(f"get_recommends: {package}: already visited")
            continue
        get_recommends_visited += [package]

        # Note that this ignores packages that don't exist. This means they
        # aren't in pmaports. This is fine, with the assumption that
        # installation will fail later in some other method if they truly don't
        # exist in any repo.
        apkbuild = pmb.helpers.pmaports.get(package, must_exist=False)
        if not apkbuild:
            continue
        if package in apkbuild["subpackages"]:
            # Just focus on the subpackage
            apkbuild = apkbuild["subpackages"][package]
            # The subpackage is None if the subpackage does not have a function
            # in the APKBUILD (uses the default function), e.g. for most openrc
            # subpackages. See pmb.parse._apkbuild._parse_subpackage().
            if not apkbuild:
                continue
        recommends = apkbuild["_pmb_recommends"]
        if recommends:
            logging.debug(f"{package}: install _pmb_recommends: {', '.join(recommends)}")
            ret += recommends
            # Call recursively in case recommends have pmb_recommends of their
            # own.
            ret += get_recommends(args, recommends)
        # Also iterate through dependencies to collect any recommends they have
        depends = apkbuild["depends"]
        if depends:
            ret += get_recommends(args, depends)

    return ret


def create_device_rootfs(args: PmbArgs, step: int, steps: int) -> None:
    # list all packages to be installed (including the ones specified by --add)
    # and upgrade the installed packages/apkindexes
    context = get_context()
    config = context.config
    device = context.config.device
    logging.info(f'*** ({step}/{steps}) CREATE DEVICE ROOTFS ("{device}") ***')

    chroot = Chroot(ChrootType.ROOTFS, device)
    pmb.chroot.init(chroot)
    # Create user before installing packages, so post-install scripts of
    # pmaports can figure out the username (legacy reasons: pmaports#820)
    set_user(context.config)

    # Fill install_packages
    install_packages = [*pmb.config.install_device_packages, "device-" + device]
    if not args.install_base:
        install_packages = [p for p in install_packages if p != "postmarketos-base"]
    ui_package_name = f"postmarketos-ui-{config.ui}"
    if config.ui.lower() != "none":
        install_packages += [ui_package_name]

    # Add additional providers of base/device/UI package
    install_packages += get_selected_providers(args, install_packages)

    install_packages += get_kernel_package(config)
    install_packages += get_nonfree_packages(device)
    if context.config.ui.lower() != "none":
        ui_package = pmb.helpers.pmaports.get(ui_package_name, subpackages=False, must_exist=False)
        if ui_package and context.config.ui_extras:
            extra = f"postmarketos-ui-{config.ui}-extras"
            extra_package = ui_package["subpackages"].get(extra)
            if extra_package:
                install_packages += [extra]

    if context.config.extra_packages.lower() != "none":
        install_packages += context.config.extra_packages.split(",")
    if args.add:
        install_packages += args.add.split(",")

    pmaports_cfg = pmb.config.pmaports.read_config()
    # postmarketos-base supports a dummy package for blocking unl0kr install
    # when not required
    if pmaports_cfg.get("supported_base_nofde", None):
        if args.full_disk_encryption:
            # Pick the most suitable unlocker depending on the packages
            # selected for installation
            unlocker = pmb.parse.depends.package_provider(
                "postmarketos-fde-unlocker", install_packages, chroot
            )
            if not unlocker:
                raise RuntimeError(
                    "Full disk encryption enabled but unable to find any suitable FDE unlocker app"
                )
            if unlocker.pkgname not in install_packages:
                install_packages += [unlocker.pkgname]
        else:
            install_packages += ["postmarketos-base-nofde"]

    pmb.helpers.repo.update(pmb.parse.deviceinfo().arch)

    # Install uninstallable "dependencies" by default
    install_packages += get_recommends(args, install_packages)

    # Install the base-systemd package first to make sure presets are available
    # when services are installed later
    if pmb.config.other.is_systemd_selected(context.config):
        pmb.chroot.apk.install(["postmarketos-base-systemd"], chroot)

    # Install all packages to device rootfs chroot (and rebuild the initramfs,
    # because that doesn't always happen automatically yet, e.g. when the user
    # installed a hook without pmbootstrap - see #69 for more info)
    # Packages will be built if necessary as part of this step
    pmb.chroot.apk.install(install_packages, chroot)
    pmb.chroot.initfs.build(chroot)

    # Set the user password
    setup_login(args, config, chroot)

    # Set the keymap if the device requires it
    setup_keymap(config, chroot)

    # Set timezone
    setup_timezone(chroot, config.timezone)

    # Set locale
    setup_locale(chroot, config.locale)

    # Set the hostname as the device name
    setup_hostname(device, config.hostname)

    setup_appstream(context.offline, chroot)

    if args.no_sshd:
        disable_service(chroot, "sshd")
    if args.no_firewall:
        disable_service(chroot, "nftables")


def install(args: PmbArgs) -> None:
    device = get_context().config.device
    chroot = Chroot(ChrootType.ROOTFS, device)
    deviceinfo = pmb.parse.deviceinfo()
    # Sanity checks
    sanity_check_boot_size()
    if not args.android_recovery_zip and args.disk:
        sanity_check_disk(args)
        sanity_check_disk_size(args)

    # --single-partition implies --no-split. There is nothing to split if
    # there is only a single partition.
    if args.single_partition:
        args.split = False
        if deviceinfo.create_initfs_extra:
            raise RuntimeError("--single-partition does not work for devices with initramfs-extra")

    # Number of steps for the different installation methods.
    if args.no_image:
        steps = 2
    elif args.android_recovery_zip:
        steps = 3
    else:
        steps = 4

    if args.zap:
        pmb.chroot.zap(False)

    # Install required programs in native chroot
    step = 1
    logging.info(f"*** ({step}/{steps}) PREPARE NATIVE CHROOT ***")
    pmb.chroot.init(Chroot.native())
    pmb.chroot.apk.install(pmb.config.install_native_packages, Chroot.native(), build=False)
    step += 1

    create_device_rootfs(args, step, steps)
    step += 1

    if args.no_image:
        return
    elif args.android_recovery_zip:
        return install_recovery_zip(args, device, deviceinfo.arch, steps)
    else:
        install_system_image(
            args,
            chroot,
            step,
            steps,
            split=args.split,
            disk=args.disk,
            single_partition=args.single_partition,
        )

    print_flash_info(
        device,
        deviceinfo,
        args.split,
        bool(args.disk and args.disk.is_absolute()),
        args.single_partition,
    )
    print_sshd_info(args)
    print_firewall_info(args.no_firewall, deviceinfo.arch)

    # Leave space before 'chroot still active' note
    logging.info("")
