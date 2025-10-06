# Copyright 2023 Clayton Craft
# SPDX-License-Identifier: GPL-3.0-or-later
from pmb.types import WithExtraRepos
import pmb.helpers

def check_option(
    ui: str, option: str, must_exist: bool = True, with_extra_repos: WithExtraRepos = "default"
) -> bool:
    """
    Check if an option, such as pmb:systemd, is inside an UI's APKBUILD.

    If must_exist is set to False, False will be returned if the UI doesn't exist.
    """
    if ui == "none":
        # Users can select "none" as UI in "pmbootstrap init", which does not
        # have a UI package.
        return False

    pkgname = f"postmarketos-ui-{ui}"
    apkbuild = pmb.helpers.pmaports.get(
        pkgname, must_exist, subpackages=False, with_extra_repos=with_extra_repos
    )
    return option in apkbuild["options"] if apkbuild is not None else False
