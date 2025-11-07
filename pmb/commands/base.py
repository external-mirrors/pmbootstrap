# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse


class Command:
    """Base class for pmbootstrap commands."""

    def run(self) -> None:
        """Run the command."""
        raise NotImplementedError()

    @staticmethod
    def add_arguments(subparser: argparse._SubParsersAction) -> argparse.ArgumentParser:
        """Set up the arguments for this command."""
        raise NotImplementedError()
