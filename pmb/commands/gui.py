# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from typing import Optional
from pmb import commands

# The gui function is optional, so we defer raising errors
# unless the user actually invoked "pmbootstrap gui".
_import_error: Optional[ImportError] = None

try:
    from pmb import gui
except ImportError as e:
    _import_error = e

class Gui(commands.Command):
    def __init__(self):
        pass

    def run(self):
        if _import_error:
            print("Error: GUI not available, ensure GTK4 and libadwaita are installed.")
            raise _import_error

        app = gui.PmbApp(application_id="org.postmarketos.Pmbootstrap")
        app.run(None)

