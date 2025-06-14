# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import enum
import os
import tempfile
from pathlib import Path
from pmb.core.arch import Arch
from pmb.core.context import get_context
from pmb.helpers import logging
from typing import Any

import pmb.build
import pmb.build.autodetect
import pmb.build.checksum
import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.other
import pmb.helpers.pmaports
import pmb.helpers.run
import pmb.parse
import pmb.parse.kconfig
from pmb.core import Chroot
from pmb.types import Apkbuild, CrossCompile, Env


class KConfigUI(enum.Enum):
    MENUCONFIG = "menuconfig"
    XCONFIG = "xconfig"
    NCONFIG = "nconfig"

    def is_graphical(self) -> bool:
        match self:
            case KConfigUI.MENUCONFIG | KConfigUI.NCONFIG:
                return False
            case KConfigUI.XCONFIG:
                return True

    def depends(self) -> list[str]:
        match self:
            case KConfigUI.MENUCONFIG:
                return ["ncurses-dev"]
            case KConfigUI.NCONFIG:
                return ["ncurses-dev"]
            case KConfigUI.XCONFIG:
                return ["qt5-qtbase-dev", "font-noto"]

    def __str__(self) -> str:
        return self.value


def get_arch(apkbuild: Apkbuild) -> Arch:
    """Take the architecture from the APKBUILD or complain if it's ambiguous.

    This function only gets called if --arch is not set.

    :param apkbuild: looks like: {"pkgname": "linux-...",
                                  "arch": ["x86_64", "armhf", "aarch64"]}

    or: {"pkgname": "linux-...", "arch": ["armhf"]}

    """
    pkgname = apkbuild["pkgname"]

    # Disabled package (arch="")
    if not apkbuild["arch"]:
        raise RuntimeError(
            f"'{pkgname}' is disabled (arch=\"\"). Please use"
            " '--arch' to specify the desired architecture."
        )

    # Multiple architectures
    if len(apkbuild["arch"]) > 1:
        raise RuntimeError(
            f"'{pkgname}' supports multiple architectures"
            f" ({', '.join(apkbuild['arch'])}). Please use"
            " '--arch' to specify the desired architecture."
        )

    return Arch.from_str(apkbuild["arch"][0])


def get_outputdir(pkgname: str, apkbuild: Apkbuild, must_exist: bool = True) -> Path:
    """Get the folder for the kernel compilation output.

    For most APKBUILDs, this is $builddir. But some older ones still use
    $srcdir/build (see the discussion in #1551).

    :param must_exist: if True, check that .config exists; if False, just return the directory
    """
    chroot = Chroot.native()

    # Old style ($srcdir/build)
    old_ret = Path(f"{pmb.config.abuild_basedir}/src/build")
    if must_exist and os.path.exists(chroot / old_ret / ".config"):
        logging.warning("*****")
        logging.warning(
            "NOTE: The code in this linux APKBUILD is pretty old."
            " Consider making a backup and migrating to a modern"
            " version with: pmbootstrap aportgen " + pkgname
        )
        logging.warning("*****")
        return old_ret

    # New style ($builddir)
    ret = ""
    if "builddir" in apkbuild:
        ret = Path(apkbuild["builddir"])

    if not must_exist:
        # For fragment-based configs, check if old style exists first
        if (chroot / old_ret).exists():
            return old_ret
        # Otherwise return the most likely directory
        # TODO: test this.. the condition is probably not correct?
        if (chroot / ret / "kernel/kernel").exists():
            return ret / "kernel"  # Mediatek style
        elif "_outdir" in apkbuild:
            return ret / apkbuild["_outdir"]  # Out-of-tree
        else:
            return ret  # Standard

    # Check all possible locations when must_exist=True
    if (chroot / ret / ".config").exists():
        return ret
    # Some Mediatek kernels use a 'kernel' subdirectory
    if (chroot / ret / "kernel/.config").exists():
        return ret / "kernel"

    # Out-of-tree builds ($_outdir)
    if (chroot / ret / apkbuild["_outdir"] / ".config").exists():
        return ret / apkbuild["_outdir"]

    # out-of-tree ($builddir)
    guess = pmb.chroot.root(
            ["find", "-maxdepth", "3", "-name", ".config"], chroot, Path(pmb.config.abuild_basedir), output_return=True
        ).rstrip()

    if guess:
        return (Path(pmb.config.abuild_basedir) / guess).parent

    # Not found
    raise RuntimeError(
        "Could not find the kernel config. Consider making a"
        " backup of your APKBUILD and recreating it from the"
        " template with: pmbootstrap aportgen " + pkgname
    )


def extract_and_patch_sources(pkgname: str, arch: Arch) -> None:
    pmb.build.copy_to_buildpath(pkgname)
    logging.info("(native) extract kernel source")
    pmb.chroot.user(["abuild", "unpack"], working_dir=Path(pmb.config.abuild_basedir))
    logging.info("(native) apply patches")
    pmb.chroot.user(
        ["abuild", "prepare"],
        working_dir=Path(pmb.config.abuild_basedir),
        output="interactive",
        env={"CARCH": str(arch)},
    )


def _make(
    chroot: pmb.core.Chroot,
    make_command: list[str],
    env: Env,
    pkgname: str,
    arch: Arch,
    apkbuild: Apkbuild,
    outputdir: Path | None = None,
) -> None:
    aport = pmb.helpers.pmaports.find(pkgname)

    if not outputdir:
        outputdir = get_outputdir(pkgname, apkbuild)

    logging.info("(native) make " + " ".join(make_command))

    pmb.chroot.user(["make", *make_command], chroot, outputdir, output="tui", env=env)

    # Find the updated config
    source = Chroot.native() / outputdir / ".config"
    if not source.exists():
        raise RuntimeError(f"No kernel config generated: {source}")

    # Update the aport (config and checksum)
    logging.info("Copy kernel config back to pmaports dir")
    config = f"config-{apkbuild['_flavor']}.{arch}"
    target = aport / config
    pmb.helpers.run.user(["cp", source, target])
    pmb.build.checksum.update(pkgname, skip_init=True)


def _init(pkgname: str, arch: Arch | None) -> tuple[str, Arch, Any, Chroot, Env]:
    """
    :returns: pkgname, arch, apkbuild, chroot, env
    """
    # Pkgname: allow omitting "linux-" prefix
    if not pkgname.startswith("linux-"):
        pkgname = "linux-" + pkgname

    aport = pmb.helpers.pmaports.find(pkgname)
    apkbuild = pmb.parse.apkbuild(aport / "APKBUILD")

    if arch is None:
        arch = get_arch(apkbuild)

    cross = pmb.build.autodetect.crosscompile(apkbuild, arch)
    logging.debug(f"Using cross: {cross.name}")
    chroot = cross.build_chroot(arch)
    hostspec = arch.alpine_triple()

    # Set up build tools and makedepends
    pmb.chroot.init(chroot)
    pmb.build.init(chroot)
    if cross.enabled():
        pmb.build.init_compiler(get_context(), [], cross, arch)

    depends = apkbuild["makedepends"] + ["gcc", "make"]

    pmb.chroot.apk.install(depends, chroot)

    extract_and_patch_sources(pkgname, arch)

    env: Env = {
        "ARCH": arch.kernel(),
    }

    if cross.enabled():
        env["CROSS_COMPILE"] = f"{hostspec}-"
        env["CC"] = f"{hostspec}-gcc"

    return pkgname, arch, apkbuild, chroot, env


def migrate_config(pkgname: str, arch: Arch | None) -> None:
    pkgname, arch, apkbuild, chroot, env = _init(pkgname, arch)
    _make(chroot, ["oldconfig"], env, pkgname, arch, apkbuild)


def edit_config(pkgname: str, arch: Arch | None, config_ui: KConfigUI) -> None:
    pkgname, arch, apkbuild, chroot, env = _init(pkgname, arch)

    pmb.chroot.apk.install(config_ui.depends(), chroot)

    # Copy host's .xauthority into native
    if config_ui.is_graphical():
        pmb.chroot.other.copy_xauthority(chroot)
        env["DISPLAY"] = os.environ.get("DISPLAY") or ":0"
        env["XAUTHORITY"] = "/home/pmos/.Xauthority"

    # Check for background color variable
    color = os.environ.get("MENUCONFIG_COLOR")
    if color:
        env["MENUCONFIG_COLOR"] = color
    mode = os.environ.get("MENUCONFIG_MODE")
    if mode:
        env["MENUCONFIG_MODE"] = mode

    _make(chroot, [str(config_ui)], env, pkgname, arch, apkbuild)


def generate_config(pkgname: str, arch: Arch | None) -> None:
    pkgname, arch, apkbuild, chroot, env = _init(pkgname, arch)

    fragments: list[str] = []
    if defconfig := apkbuild.get("_defconfig"):
        fragments += defconfig

    # Generate fragment based on categories for kernel, using kconfigcheck.toml
    pmos_frag, syms_dict = pmb.parse.kconfig.create_fragment(apkbuild, arch)

    # Write the pmos fragment to the kernel source tree
    outputdir = get_outputdir(pkgname, apkbuild, must_exist=False)
    arch_configs_dir = outputdir / "arch" / arch.kernel() / "configs"

    # Create the configs directory if it doesn't exist
    pmb.chroot.user(
        ["mkdir", "-p", str(arch_configs_dir)], chroot, working_dir=Path(pmb.config.abuild_basedir)
    )

    # Write the pmos fragment to a temp file and copy it in
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as pmos_frag_file:
        pmos_frag_file.write(pmos_frag)
    try:
        # Copy the temp file to the configs directory
        pmb.helpers.run.root(
            [
                "cp",
                pmos_frag_file.name,
                f"{Chroot.native() / arch_configs_dir}/pmos_generated.config",
            ]
        )
    finally:
        os.unlink(pmos_frag_file.name)

    fragments.append("pmos_generated.config")

    # Parse fragments before copying to track expected options
    aport = pmb.helpers.pmaports.find(pkgname)
    fragment_options: dict[str, dict[str, bool | str | list[str]]] = {}

    # Collect and parse other fragments from the kernel package directory
    for config_file in aport.glob("*.config"):
        # Parse the fragment
        with open(config_file) as f:
            fragment_options[config_file.name] = parse_fragment(f.read())

        # Copy fragment to arch/$arch/configs in kernel source
        pmb.helpers.run.root(
            ["cp", str(config_file), f"{Chroot.native() / arch_configs_dir}/{config_file.name}"]
        )
        if config_file.name not in fragments:
            fragments.append(config_file.name)

    # Fixup fragments' permissions
    pmb.chroot.root(["chown", "-R", "pmos:pmos", str(arch_configs_dir)])

    # Generate the config using all fragments
    _make(chroot, fragments, env, pkgname, arch, apkbuild, outputdir)

    print("Parsing kconfig!")
    pmb.parse.kconfig.add_missing_dependencies(apkbuild, syms_dict, outputdir / ".config")

    # Validate the generated config
    if not pmb.parse.kconfig.check(pkgname, details=True):
        raise RuntimeError("Generated kernel config does not pass all checks")

    # Validate that all fragment options made it to the final config
    final_config_path = aport / f"config-{apkbuild['_flavor']}.{arch}"
    with open(final_config_path) as f:
        final_config = f.read()

    validation_failed = False
    for fragment_name, options in fragment_options.items():
        for option, expected_value in options.items():
            if isinstance(expected_value, bool):
                if expected_value:
                    # Option should be set (=y or =m)
                    if not pmb.parse.kconfig.is_set(final_config, option):
                        logging.error(
                            f"Fragment {fragment_name}: CONFIG_{option} was not enabled in final config (missing dependencies?)"
                        )
                        validation_failed = True
                else:
                    # Option should not be set
                    if pmb.parse.kconfig.is_set(final_config, option):
                        logging.error(
                            f"Fragment {fragment_name}: CONFIG_{option} should not be set but is enabled in final config"
                        )
                        validation_failed = True
            elif isinstance(expected_value, str):
                if not pmb.parse.kconfig.is_set_str(final_config, option, expected_value):
                    logging.error(
                        f"Fragment {fragment_name}: CONFIG_{option} expected to be '{expected_value}' but has different value in final config"
                    )
                    validation_failed = True
            elif isinstance(expected_value, list):
                for value in expected_value:
                    if not pmb.parse.kconfig.is_in_array(final_config, option, value):
                        logging.error(
                            f"Fragment {fragment_name}: CONFIG_{option} expected to contain '{value}' but doesn't in final config"
                        )
                        validation_failed = True

    if validation_failed:
        raise RuntimeError(
            "Fragment validation failed: Some options from fragments did not make it to the final kernel config. This usually means missing dependencies."
        )


def parse_fragment(content: str) -> dict[str, bool | str | list[str]]:
    """Parse a kconfig fragment and return a dict of options and their values."""
    options: dict[str, bool | str | list[str]] = {}

    for line in content.splitlines():
        line = line.strip()

        # Skip empty lines and comments (except "is not set" lines)
        if not line or (line.startswith("#") and "is not set" not in line):
            continue

        # Handle "is not set" format
        if "# CONFIG_" in line and "is not set" in line:
            # Extract option name from "# CONFIG_OPTION is not set"
            option = line.split("CONFIG_")[1].split(" ")[0]
            options[option] = False
            continue

        # Handle regular CONFIG_OPTION=value format
        if line.startswith("CONFIG_"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                option = parts[0].removeprefix("CONFIG_")
                value = parts[1]

                # Boolean options (y/m)
                if value in ["y", "m"]:
                    options[option] = True
                # String options
                elif value.startswith('"') and value.endswith('"'):
                    # Remove quotes and check for comma-separated list
                    value_unquoted = value[1:-1]
                    if "," in value_unquoted:
                        options[option] = value_unquoted.split(",")
                    else:
                        options[option] = value_unquoted
                # Numeric or other options (treat as string)
                else:
                    options[option] = value

    return options
