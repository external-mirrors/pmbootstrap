# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import enum
import os
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
from pmb.types import Apkbuild, Env, RunOutputTypeDefault


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
    old_ret = Path("/home/pmos/build/src/build")
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
    cmd = "srcdir=/home/pmos/build/src source APKBUILD; echo $builddir"
    ret = Path(
        pmb.chroot.user(
            ["sh", "-c", cmd], chroot, Path("/home/pmos/build"), output_return=True
        ).rstrip()
    )

    if not must_exist:
        # For fragment-based configs, check if old style exists first
        if (chroot / old_ret).exists():
            return old_ret
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

    # Not found
    raise RuntimeError(
        "Could not find the kernel config. Consider making a"
        " backup of your APKBUILD and recreating it from the"
        " template with: pmbootstrap aportgen " + pkgname
    )


def extract_and_patch_sources(pkgname: str, arch: Arch) -> None:
    pmb.build.copy_to_buildpath(pkgname)
    logging.info("(native) extract kernel source")
    pmb.chroot.user(["abuild", "unpack"], working_dir=Path("/home/pmos/build"))
    logging.info("(native) apply patches")
    pmb.chroot.user(
        ["abuild", "prepare"],
        working_dir=Path("/home/pmos/build"),
        output=RunOutputTypeDefault.INTERACTIVE,
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

    pmb.chroot.user(
        ["make", *make_command], chroot, outputdir, output=RunOutputTypeDefault.TUI, env=env
    )

    # Find the updated config
    source = Chroot.native() / outputdir / ".config"
    if not source.exists():
        raise RuntimeError(f"No kernel config generated: {source}")

    # Update the aport (config and checksum)
    logging.info("Copy kernel config back to pmaports dir")
    config = f"config-{apkbuild['_flavor']}.{arch}"
    target = aport / config
    pmb.helpers.run.user(["cp", source, target])
    pmb.build.checksum.update(pkgname)


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
    chroot = cross.build_chroot(arch)
    hostspec = arch.alpine_triple()

    # Set up build tools and makedepends
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


def edit_config(
    pkgname: str, arch: Arch | None, config_ui: KConfigUI, fragment: str | None
) -> None:
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

    if fragment:
        aport = pmb.helpers.pmaports.find(pkgname)
        config_name = f"config-{apkbuild['_flavor']}.{arch}"
        full_config = aport / config_name

        if not full_config.exists():
            raise RuntimeError(
                f"Full config not found: {full_config}. "
                f"Run 'pmbootstrap kconfig generate {pkgname}' first."
            )

        with open(full_config) as f:
            baseline_config = f.read()

    _make(chroot, [str(config_ui)], env, pkgname, arch, apkbuild)

    if fragment:
        with open(full_config) as f:
            new_config = f.read()
        _extract_config_diff(new_config, baseline_config, aport / fragment)

        logging.info("Validating fragment changes...")
        generate_config(pkgname, arch)
        logging.info(f"Fragment saved to {fragment}")


def _parse_config_options(config_content: str) -> dict[str, str]:
    """Parse kernel config content into a dict of options."""
    opts = {}
    for line in config_content.splitlines():
        line = line.strip()
        if line.startswith("CONFIG_"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                opts[parts[0]] = parts[1]
        elif "is not set" in line and "CONFIG_" in line:
            opt = line.split("CONFIG_")[1].split()[0]
            opts[f"CONFIG_{opt}"] = "n"
    return opts


def _extract_config_diff(new_config: str, baseline_config: str, output: Path) -> None:
    """Extract differences between two kernel configs into a fragment."""

    baseline_opts = _parse_config_options(baseline_config)
    new_opts = _parse_config_options(new_config)

    # Iterate through the differences between each config and build a fragment
    changes = []
    for opt in sorted(set(baseline_opts.keys()) | set(new_opts.keys())):
        baseline_val = baseline_opts.get(opt)
        new_val = new_opts.get(opt)

        if baseline_val != new_val:
            # "is not set" config changes are represented as "n"
            if new_val == "n":
                changes.append(f"# {opt} is not set")
            elif new_val:
                changes.append(f"{opt}={new_val}")

    if len(changes) == 0:
        logging.info("No configuration changes detected")
    else:
        with open(output, "w") as f:
            f.write("# Generated by pmbootstrap kconfig edit\n")
            f.write("\n".join(changes))


def generate_config(pkgname: str, arch: Arch | None) -> None:
    pkgname, arch, apkbuild, chroot, env = _init(pkgname, arch)

    fragments: list[str] = []
    if defconfig := apkbuild.get("_defconfig"):
        fragments += defconfig

    # The 'pmos fragment' is generated from kconfigcheck.toml
    pmos_frag = pmb.parse.kconfig.create_fragment(apkbuild, arch)

    # Write the pmos fragment to the aports dir and copy it into the kernel source tree
    aport = pmb.helpers.pmaports.find(pkgname)
    outputdir = get_outputdir(pkgname, apkbuild, must_exist=False)
    arch_configs_dir = outputdir / "arch" / arch.kernel() / "configs"
    pmb.chroot.user(
        ["mkdir", "-p", str(arch_configs_dir)], chroot, working_dir=Path("/home/pmos/build")
    )
    with open(aport / "pmos.config", mode="w") as pmos_frag_file:
        pmos_frag_file.write(pmos_frag)
        pmb.helpers.run.root(
            [
                "cp",
                pmos_frag_file.name,
                f"{Chroot.native() / arch_configs_dir}/pmos_generated.config",
            ]
        )
    fragments.append("pmos.config")

    # Collect and parse other fragments from the kernel package directory
    fragment_options: dict[str, dict[str, bool | str | list[str]]] = {}
    for config_file in aport.glob("*.config"):
        with open(config_file) as f:
            fragment_options[config_file.name] = parse_fragment(f.read())

        # Copy fragment to arch/$arch/configs in kernel source
        pmb.helpers.run.root(
            ["cp", str(config_file), f"{Chroot.native() / arch_configs_dir}/{config_file.name}"]
        )
        if config_file.name not in fragments:
            fragments.append(config_file.name)

    # pmos user needs to be able to R/W this or else _make fails
    pmb.chroot.root(["chown", "-R", "pmos:pmos", str(arch_configs_dir)])

    # Generate the config using all fragments
    _make(chroot, fragments, env, pkgname, arch, apkbuild, outputdir)

    # Validate that all fragment options made it to the final config
    if not pmb.parse.kconfig.check(pkgname, details=True):
        raise RuntimeError("Generated kernel config does not pass all checks")

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
