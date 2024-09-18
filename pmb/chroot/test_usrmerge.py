from pmb.core import Chroot
from .init import init as init_chroot, UsrMerge


def test_usr_merge_symlinks(pmaports, chroot_cleanup):
    chroot = Chroot.native()
    init_chroot(chroot, UsrMerge.ON)

    # Make sure all the symlinks have been created
    assert (chroot / "bin").is_symlink()
    assert (chroot / "lib").is_symlink()
    assert (chroot / "usr/sbin").is_symlink()

    # Ensure they resolve correctly inside the chroot and don't
    # point to the host system
    assert (chroot / "bin").resolve() == chroot / "usr/bin"
    assert (chroot / "lib").resolve() == chroot / "usr/lib"
    assert (chroot / "usr/sbin").resolve() == chroot / "usr/bin"
