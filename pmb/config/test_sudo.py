import os
import pytest
from pmb.config.sudo import which_sudo, PMB_SUDO_ENV_KEY


def test_sudo_override(monkeypatch):
    """check sudo is used when PMB_SUDO_ENV_KEY is set to sudo"""
    monkeypatch.setenv(PMB_SUDO_ENV_KEY, "sudo")
    which_sudo.cache_disable()
    assert which_sudo() == "sudo"


def test_using_doas_default(monkeypatch):
    """check doas is used when PMB_SUDO_ENV_KEY not defined"""
    monkeypatch.delenv(PMB_SUDO_ENV_KEY, raising=False)
    which_sudo.cache_disable()
    assert which_sudo() == "doas"


def test_bad_env(monkeypatch):
    """check error is raised when PMB_SUDO_ENV_KEY is misspelled"""
    monkeypatch.setenv(PMB_SUDO_ENV_KEY, "doass")
    which_sudo.cache_disable()
    with pytest.raises(RuntimeError):
        which_sudo()


def test_already_root(monkeypatch):
    """which_sudo should be None if pmbootstrap ran as root"""

    def root_getuid():
        return 0

    which_sudo.cache_disable()
    monkeypatch.setattr(os, "getuid", root_getuid)
    assert which_sudo() is None
