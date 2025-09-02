# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later


class Command:
    """Base class for pmbootstrap commands."""

    def run(self) -> None:
        """Run the command."""
        raise NotImplementedError()

    @staticmethod
    def choices(arg: str) -> tuple[str]:
        """Get the available choices for an argument"""
        raise NotImplementedError()
