# Copyright 2023 Oliver Smith
# Copyright 2024 Stefan Hansson
# SPDX-License-Identifier: GPL-3.0-or-later

import pmb.parse.deviceinfo
from pmb import commands
from pmb.core.context import get_context
from pmb.flasher.frontend import flash_lk2nd, kernel, list_flavors, rootfs, sideload
from pmb.helpers import logging

import argparse


class Flasher(commands.Command):
    def __init__(
        self,
        action_flasher: str,
        autoinstall: bool,
        cmdline: str | None,
        flash_method: str,
        no_reboot: bool | None,
        partition: str | None,
        resume: bool | None,
    ) -> None:
        self.action_flasher = action_flasher
        self.autoinstall = autoinstall
        self.cmdline = cmdline
        self.flash_method = flash_method
        self.no_reboot = no_reboot
        self.partition = partition
        self.resume = resume

    def run(self) -> None:
        context = get_context()
        action = self.action_flasher
        device = context.config.device
        deviceinfo = pmb.parse.deviceinfo()
        method = self.flash_method or deviceinfo.flash_method

        if method == "none" and action in ["boot", "flash_kernel", "flash_rootfs", "flash_lk2nd"]:
            logging.info("This device doesn't support any flash method.")
            return

        if action in ["boot", "flash_kernel"]:
            kernel(
                deviceinfo,
                method,
                action == "boot",
                self.autoinstall,
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "flash_rootfs":
            rootfs(
                deviceinfo,
                method,
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "flash_vbmeta":
            logging.info("(native) flash vbmeta.img with verity disabled flag")
            pmb.flasher.run(
                deviceinfo,
                method,
                "flash_vbmeta",
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "flash_dtbo":
            logging.info("(native) flash dtbo image")
            pmb.flasher.run(
                deviceinfo,
                method,
                "flash_dtbo",
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "flash_lk2nd":
            flash_lk2nd(
                deviceinfo,
                method,
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "list_flavors":
            list_flavors(device)
        elif action == "list_devices":
            pmb.flasher.run(
                deviceinfo,
                method,
                "list_devices",
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )
        elif action == "sideload":
            sideload(
                deviceinfo,
                method,
                cmdline=self.cmdline,
                no_reboot=self.no_reboot,
                partition=self.partition,
                resume=self.resume,
            )

    @staticmethod
    def add_arguments(subparser: argparse._SubParsersAction) -> argparse.ArgumentParser:
        ret = subparser.add_parser("flasher", help="flash something to the target device")
        ret.add_argument(
            "--method", help="override flash method", dest="flash_method", default=None
        )
        sub = ret.add_subparsers(dest="action_flasher")
        sub.required = True

        # Boot, flash kernel
        boot = sub.add_parser("boot", help="boot a kernel once")
        boot.add_argument("--cmdline", help="override kernel commandline")
        flash_kernel = sub.add_parser("flash_kernel", help="flash a kernel")
        for action in [boot, flash_kernel]:
            action.add_argument(
                "--no-install",
                dest="autoinstall",
                default=True,
                help="skip updating kernel/initfs",
                action="store_false",
            )
        flash_kernel.add_argument(
            "--partition",
            default=None,
            help="partition to flash the kernel to (defaults to deviceinfo_flash_*_partition_kernel)",
        )

        # Flash lk2nd
        flash_lk2nd = sub.add_parser(
            "flash_lk2nd",
            help="flash lk2nd, a secondary bootloader needed for various Android devices",
        )
        flash_lk2nd.add_argument(
            "--partition",
            default=None,
            help="partition to flash lk2nd to (defaults to default boot image partition ",
        )

        # Flash rootfs
        flash_rootfs = sub.add_parser(
            "flash_rootfs",
            help="flash the rootfs to a partition on the"
            " device (partition layout does not get"
            " changed)",
        )
        flash_rootfs.add_argument(
            "--partition",
            default=None,
            help="partition to flash the rootfs to (defaults"
            " to deviceinfo_flash_*_partition_rootfs,"
            " 'userdata' on Android may have more"
            " space)",
        )

        # Flash vbmeta
        flash_vbmeta = sub.add_parser(
            "flash_vbmeta",
            help="generate and flash AVB 2.0 image with"
            " disable verification flag set to a"
            " partition on the device (typically called"
            " vbmeta)",
        )
        flash_vbmeta.add_argument(
            "--partition",
            default=None,
            help="partition to flash the vbmeta to (defaults to deviceinfo_flash_*_partition_vbmeta",
        )

        # Flash dtbo
        flash_dtbo = sub.add_parser("flash_dtbo", help="flash dtbo image")
        flash_dtbo.add_argument(
            "--partition",
            default=None,
            help="partition to flash the dtbo to (defaults to deviceinfo_flash_*_partition_dtbo)",
        )

        # Actions without extra arguments
        sub.add_parser("sideload", help="sideload recovery zip")
        sub.add_parser(
            "list_flavors",
            help="list installed kernel flavors"
            + " inside the device rootfs chroot on this computer",
        )
        sub.add_parser("list_devices", help="show connected devices")

        group = ret.add_argument_group(
            "heimdall options",
            "With heimdall as"
            " flash method, the device automatically"
            " reboots after each flash command. Use"
            " --no-reboot and --resume for multiple"
            " flash actions without reboot.",
        )
        group.add_argument(
            "--no-reboot",
            dest="no_reboot",
            help="don't automatically reboot after flashing",
            action="store_true",
        )
        group.add_argument(
            "--resume",
            dest="resume",
            help="resume flashing after using --no-reboot",
            action="store_true",
        )

        return ret
