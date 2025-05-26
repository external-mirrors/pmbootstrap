# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse


class Command:
    """Base class for pmbootstrap commands."""

    def run(self) -> None:
        """Run the command."""
        raise NotImplementedError()

    def parse(self, parser: argparse.ArgumentParser) -> None:
        """Ensure arguments are correct, call parser.error() otherwise"""
