# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path
import sys
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw # type: ignore

_path = Path(__file__).parent

# sobbing
os.chdir(_path)
os.system("glib-compile-resources pmbootstrap.gresource.xml")
os.chdir(os.environ["OLDPWD"])

from gi.repository import Gio # type: ignore
resource = Gio.Resource.load(os.fspath(_path / "pmbootstrap.gresource"))
resource._register()


@Gtk.Template(resource_path='/org/postmarketos/pmbootstrap/ui/main.ui')
class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MainWindow"

    main_content = Gtk.Template.Child()
    sidebar_break = Gtk.Template.Child()
    split_view = Gtk.Template.Child()
    nav = Gtk.Template.Child()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_manager = Adw.StyleManager().get_default()


class PmbApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

