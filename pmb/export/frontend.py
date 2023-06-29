import glob
import logging
import os

import pmb.helpers.run
import pmb.helpers.frontend
import pmb.chroot.initfs
import pmb.export
from pmb.core import Suffix, SuffixType


def frontend(args):
    # Create the export folder
    target = args.export_folder
    if not os.path.exists(target):
        pmb.helpers.run.user(args, ["mkdir", "-p", target])

    # Rootfs image note
    chroot = args.work + f"/{Suffix.native().chroot()}"
    pattern = chroot + "/home/pmos/rootfs/" + args.device + "*.img"
    if not glob.glob(pattern):
        logging.info("NOTE: To export the rootfs image, run 'pmbootstrap"
                     " install' first (without the 'disk' parameter).")

    # Rebuild the initramfs, just to make sure (see #69)
    flavor = pmb.helpers.frontend._parse_flavor(args, args.autoinstall)
    if args.autoinstall:
        pmb.chroot.initfs.build(args, flavor, Suffix(SuffixType.ROOTFS, args.device))

    # Do the export, print all files
    logging.info("Export symlinks to: " + target)
    if args.odin_flashable_tar:
        pmb.export.odin(args, flavor, target)
    pmb.export.symlinks(args, flavor, target)
