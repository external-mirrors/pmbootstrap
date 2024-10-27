from pathlib import Path
from .deviceinfo import Deviceinfo
from pmb.config import deviceinfo_chassis_types

import pytest
import tempfile
import random

# Exported from the wiki using https://www.convertcsv.com/html-table-to-csv.htm
# on 2024/10/23
deviceinfo_keys = [
    "format_version",
    "name",
    "manufacturer",
    "codename",
    "uboot_boardname",
    "year",
    "chassis",
    "dtb",
    "append_dtb",
    "external_storage",
    "flash_method",
    "arch",
    "dev_internal_storage",
    "dev_internal_storage_repartition",
    "dev_touchscreen",
    "dev_touchscreen_calibration",
    "keymaps",
    "swap_size_recommended",
    "zram_swap_pct",
    "tmp_as_tmpfs_size",
    "disable_dhcpd",
    "no_framebuffer",
    "initfs_compression",
    "create_initfs_extra",
    "getty",
    "gpu_accelerated",
    "super_partitions",
    "Variable",
    "flash_offset_base",
    "flash_offset_dtb",
    "flash_offset_kernel",
    "flash_offset_ramdisk",
    "flash_offset_second",
    "flash_offset_tags",
    "flash_pagesize",
    "flash_sparse",
    "flash_sparse_samsung_format",
    "flash_kernel_on_update",
    "kernel_cmdline",
    "kernel_cmdline_append",
    "bootimg_amazon_omap_header_size",
    "bootimg_blobpack",
    "bootimg_qcdt",
    "bootimg_qcdt_type",
    "bootimg_mtk_label_kernel",
    "bootimg_mtk_label_ramdisk",
    "bootimg_override_payload",
    "bootimg_override_initramfs",
    "bootimg_override_payload_compression",
    "deviceinfo_bootimg_prepend_dhtb",
    "bootimg_override_payload_append_dtb",
    "bootimg_dtb_second",
    "bootimg_append_seandroidenforce",
    "bootimg_pxa",
    "bootimg_custom_args",
    "header_version",
    "generate_bootimg",
    "generate_extlinux_config",
    "generate_grub_config",
    "generate_systemd_boot",
    "generate_uboot_fit_images",
    "generate_legacy_uboot_initfs",
    "legacy_uboot_load_address",
    "legacy_uboot_image_name",
    "flash_fastboot_partition_kernel",
    "flash_fastboot_partition_system",
    "flash_fastboot_partition_vbmeta",
    "flash_fastboot_partition_dtbo",
    "flash_fastboot_max_size",
    "flash_heimdall_partition_kernel",
    "flash_heimdall_partition_initfs",
    "flash_heimdall_partition_system",
    "flash_heimdall_partition_vbmeta",
    "flash_rk_partition_kernel",
    "flash_rk_partition_system",
    "flash_mtkclient_partition_kernel",
    "flash_mtkclient_partition_rootfs",
    "flash_mtkclient_partition_vbmeta",
    "flash_mtkclient_partition_dtbo",
    "boot_filesystem",
    "root_filesystem",
    "rootfs_image_sector_size",
    "sd_embed_firmware",
    "sd_embed_firmware_step_size",
    "partition_blacklist",
    "boot_part_start",
    "partition_type",
    "mkinitfs_postprocess",
    "Variable",
    "bootimg_vendor_dependent",
    "bootimg_vendor_android_boot_image",
    "bootimg_vendor_device_tree_identifiers",
    "Variable",
    "screen_width",
    "screen_height",
    "Variable",
    "usb_idVendor",
    "usb_idProduct",
    "usb_serialnumber",
    "usb_network_function",
    "usb_network_udc",
    "Variable",
    "cgpt_kpart",
    "cgpt_kpart_start",
    "cgpt_kpart_size",
    "depthcharge_board",
    "generate_depthcharge_image",
]

deprecated_keys = [
    "flash_methods",
    "external_disk",
    "external_disk_install",
    "msm_refresher",
    "flash_fastboot_vendor_id",
    "nonfree",
    "dev_keyboard",
    "date",
]

required_keys = [
    "codename",
    "chassis",
    "arch",
]

# Guaranteed by fair dice roll
random_values = [
    "",
    "test",
    "True",
    "false",
    "2020",
    "0xf100f",
    "843772384",
    "0",
    "1",
    "///@@",
    "/34u3294£$*R",
]


@pytest.fixture
def monkeypatch_deviceinfo(monkeypatch):
    monkeypatch.setenv("PMBOOTSTRAP_TEST_DEVICEINFO_PARSING", "1")


def random_deviceinfo_props(nprops=10):
    props = {}
    for _ in range(nprops):
        key = random.choice(deviceinfo_keys)
        value = random.choice(random_values)
        props[key] = value

    return props


def random_valid_deviceinfo(tmp_path):
    _, name = tempfile.mkstemp(dir=tmp_path)
    path = Path(name)

    info = random_deviceinfo_props(random.randint(1, len(deviceinfo_keys)))

    # Set the required properties
    # This would be the device package dir...
    info["codename"] = tmp_path.name[7:]
    info["chassis"] = random.choice(deviceinfo_chassis_types)
    info["arch"] = random.choice(["armhf", "aarch64", "x86_64"])

    # Now write it all out to a file
    with open(path, "w") as f:
        for key, value in info.items():
            f.write(f'deviceinfo_{key}="{value}"\n')

    return path


# Test deviceinfo files that are technically valid but have bogus data
# These are expected to get more strict as the parser is improved
def test_random_valid_deviceinfos(tmp_path, monkeypatch_deviceinfo):
    for _ in range(1000):
        info_path = random_valid_deviceinfo(tmp_path)
        print(f"Testing randomly generate deviceinfo file {info_path}")
        info = Deviceinfo(info_path)
        print(info.codename)


# Check that lines starting with deviceinfo_ but don't have an
# "=" raise a syntax error
def test_syntax_error(tmp_file):
    with open(tmp_file, "w") as f:
        f.write('deviceinfo_codename="test"\n')
        f.write('deviceinfo_chassis="test"\n')
        f.write('deviceinfo_arch="test"\n')
        f.write("deviceinfo_nothing??\n\n\n")

    with pytest.raises(SyntaxError):
        Deviceinfo(tmp_file)
