# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from pmb import commands
from enum import Enum
import pmb.parse


# python 3.10 doesn't have StrEnum
class InspectProperty(Enum):
    ARCH = "arch"
    DEVICEINFO = "deviceinfo"

    def __str__(self) -> str:
        return self.name


class Inspect(commands.Command):
    def __init__(self, prop: str) -> None:
        self.property: InspectProperty = InspectProperty(prop)

    @staticmethod
    def choices(arg: str) -> tuple[str]:
        match arg:
            case "property":
                # mypy thinks this is tuple[InspectProperty, ...] for some reason
                return tuple(x.lower() for x in InspectProperty._member_names_)  # type: ignore
            case _:
                raise ValueError()

    def run(self) -> None:
        info = pmb.parse.deviceinfo()
        match self.property:
            case InspectProperty.ARCH:
                print(info.arch)
            case InspectProperty.DEVICEINFO:
                print(info.to_json())
