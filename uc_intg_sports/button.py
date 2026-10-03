"""
Sports button entity: refresh now.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

from typing import Any

from ucapi import StatusCodes
from ucapi.button import Attributes, Commands, States
from ucapi_framework import ButtonEntity

from uc_intg_sports.config import SportsConfig
from uc_intg_sports.device import SportsDevice


class SportsRefreshButton(ButtonEntity):
    def __init__(self, device_config: SportsConfig, device: SportsDevice) -> None:
        self._device = device
        super().__init__(
            f"button.{device_config.identifier}.refresh",
            f"{device_config.name} Refresh",
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        state = States.UNAVAILABLE if self._device.state == "UNAVAILABLE" else States.AVAILABLE
        self.update({Attributes.STATE: state})

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        if cmd_id != Commands.PUSH:
            return StatusCodes.NOT_IMPLEMENTED
        await self._device.refresh()
        return StatusCodes.OK


def create_buttons(device_config: SportsConfig, device: SportsDevice) -> list[SportsRefreshButton]:
    return [SportsRefreshButton(device_config, device)]
