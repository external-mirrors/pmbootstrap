# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import configparser
import os
import pmb.config

config: configparser.ConfigParser | None = None
runtime_override = {"aports": None, "work": None}

def load(args):
    global config

    if config is not None:
        return config

    for key in runtime_override:
        if getattr(args, key) is not None:
            runtime_override[key] = getattr(args, key)

    cfg = configparser.ConfigParser()
    if os.path.isfile(args.config):
        cfg.read(args.config)

    if "pmbootstrap" not in cfg:
        cfg["pmbootstrap"] = {}
    if "providers" not in cfg:
        cfg["providers"] = {}

    for key in pmb.config.defaults:
        if key in pmb.config.config_keys and key not in cfg["pmbootstrap"]:
            cfg["pmbootstrap"][key] = str(pmb.config.defaults[key])

        # We used to save default values in the config, which can *not* be
        # configured in "pmbootstrap init". That doesn't make sense, we always
        # want to use the defaults from pmb/config/__init__.py in that case,
        # not some outdated version we saved some time back (eg. aports folder,
        # postmarketOS binary packages mirror).
        if key not in pmb.config.config_keys and key in cfg["pmbootstrap"]:
            logging.debug("Ignored unconfigurable and possibly outdated"
                          " default value from config:"
                          f" {cfg['pmbootstrap'][key]}")
            del cfg["pmbootstrap"][key]

    config = cfg
    return cfg


def get(key, with_overrides=True):
    global config
    if not config:
        raise RuntimeError("pmb.config.get() called before pmb.config.load()!")

    if with_overrides:
        if runtime_override["aports"] is not None and key == "aports":
            return runtime_override["aports"] + "," + config["pmbootstrap"][key]
        if runtime_override["work"] is not None and key == "work":
            return runtime_override["work"]

    return config["pmbootstrap"][key]


def save(args, cfg):
    logging.debug("Save config: " + args.config)
    os.makedirs(os.path.dirname(args.config), 0o700, True)
    with open(args.config, "w") as handle:
        cfg.write(handle)



def merge_with_args(args):
    """
    We have the internal config (pmb/config/__init__.py) and the user config
    (usually ~/.config/pmbootstrap.cfg, can be changed with the '-c'
    parameter).

    Args holds the variables parsed from the commandline (e.g. -j fills out
    args.jobs), and values specified on the commandline count the most.

    In case it is not specified on the commandline, for the keys in
    pmb.config.config_keys, we look into the value set in the the user config.

    When that is empty as well (e.g. just before pmbootstrap init), or the key
    is not in pmb.config_keys, we use the default value from the internal
    config.
    """
    # Use defaults from the user's config file
    cfg = pmb.config.load(args)
    for key in cfg["pmbootstrap"]:
        if key not in args or getattr(args, key) is None:
            value = cfg["pmbootstrap"][key]
            if key in pmb.config.defaults:
                default = pmb.config.defaults[key]
                if isinstance(default, bool):
                    value = (value.lower() == "true")
            setattr(args, key, value)
    setattr(args, 'selected_providers', cfg['providers'])

    # Use defaults from pmb.config.defaults
    for key, value in pmb.config.defaults.items():
        if key not in args or getattr(args, key) is None:
            setattr(args, key, value)
