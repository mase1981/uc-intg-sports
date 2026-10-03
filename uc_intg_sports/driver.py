"""
Sports driver for Unfolded Circle Remote.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from ucapi_framework import BaseIntegrationDriver

from uc_intg_sports.button import create_buttons
from uc_intg_sports.config import SportsConfig
from uc_intg_sports.device import SportsDevice
from uc_intg_sports.media_player import create_media_players
from uc_intg_sports.select import create_selects
from uc_intg_sports.sensor import create_sensors


class SportsDriver(BaseIntegrationDriver[SportsDevice, SportsConfig]):
    """Sports integration driver."""

    def __init__(self):
        super().__init__(
            device_class=SportsDevice,
            entity_classes=[create_media_players, create_selects, create_sensors, create_buttons],
            driver_id="sports",
        )
