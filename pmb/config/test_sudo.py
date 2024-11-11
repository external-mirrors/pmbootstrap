import os
import pytest
from pmb.config.sudo import which_sudo


def test_sudo_override(monkeypatch):
    """check sudo is used when PMB_SUDO is set to sudo"""
    monkeypatch.setenv("PMB_SUDO", "sudo")
    assert which_sudo() == "sudo"


def test_using_doas_default(monkeypatch):
    """check doas is used when PMB_SUDO not defined"""
    monkeypatch.delenv("PMB_SUDO", raising=False)
    assert which_sudo() == "doas"


def test_bad_env(monkeypatch):
    """check error is raised when PMB_SUDO is misspelled"""
    monkeypatch.setenv("PMB_SUDO", "doass")
    with pytest.raises(RuntimeError):
        which_sudo()


def test_already_root(monkeypatch):
    """which_sudo should be None if pmbootstrap ran as root"""

    def root_getuid():
        return 0

    monkeypatch.setattr(os, "getuid", root_getuid)
    assert which_sudo() is None
