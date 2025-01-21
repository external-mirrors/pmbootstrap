# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib

def xhash(val: str) -> str:
    """
    Hash a string to sha1 (for caching purposes only! Not secure!)
    """
    return hashlib.sha1(val.encode()).hexdigest()
