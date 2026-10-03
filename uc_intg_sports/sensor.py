"""
Sports sensor entities.

Text sensors for Remote pages and activities. Times follow the display
preferences (12/24-hour, date format, time zone).

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import Callable

from ucapi.sensor import Attributes, DeviceClasses, States
from ucapi_framework import SensorEntity

from uc_intg_sports.config import SportsConfig
from uc_intg_sports.device import SportsDevice
from uc_intg_sports.prefs import fmt_kickoff, matchup, score_line, status_label

_LOG = logging.getLogger(__name__)


def _score(device: SportsDevice) -> str | None:
    game = device.live_game() or device.last_result()
    return score_line(game, device.prefs) if game else None


def _status(device: SportsDevice) -> str | None:
    soccer = device.league.is_soccer
    live = device.live_game()
    if live is not None:
        return f"Live {status_label(live, soccer)}"
    game = device.current_game()
    if game is None:
        return "No games scheduled" if device.has_data else None
    if game.state == "post":
        return status_label(game, soccer)
    return "Upcoming"


def _next_game(device: SportsDevice) -> str | None:
    game = device.next_game()
    return matchup(game, device.prefs) if game else ("None scheduled" if device.has_data else None)


def _kickoff(device: SportsDevice) -> str | None:
    game = device.next_game()
    return fmt_kickoff(game, device.prefs) if game else ("None scheduled" if device.has_data else None)


def _last_result(device: SportsDevice) -> str | None:
    game = device.last_result()
    if game is None:
        return None
    mine, theirs = game.side_of(device.team_id), game.opponent_of(device.team_id)
    if mine is None or theirs is None:
        return score_line(game, device.prefs)
    outcome = "W" if mine.winner else "L" if theirs.winner else "D" if device.league.is_soccer else "T"
    if mine.shootout or theirs.shootout:
        outcome = "W" if mine.winner else "L"
    venue = "v" if game.home.team.id == device.team_id else "@"
    return f"{outcome} {mine.score}-{theirs.score} {venue} {theirs.team.name}"


def _standing(device: SportsDevice) -> str | None:
    return device.info.standing or None if device.info else None


def _record(device: SportsDevice) -> str | None:
    return device.info.record or None if device.info else None


_SENSORS: tuple[tuple[str, str, Callable[[SportsDevice], str | None]], ...] = (
    ("score", "Score", _score),
    ("status", "Game Status", _status),
    ("next_game", "Next Game", _next_game),
    ("kickoff", "Next Kickoff", _kickoff),
    ("last_result", "Last Result", _last_result),
    ("standing", "Standing", _standing),
    ("record", "Record", _record),
)


class SportsSensor(SensorEntity):
    def __init__(
        self, device_config: SportsConfig, device: SportsDevice, key: str, label: str,
        read: Callable[[SportsDevice], str | None],
    ) -> None:
        self._device = device
        self._read = read
        super().__init__(
            f"sensor.{device_config.identifier}.{key}",
            f"{device_config.name} {label}",
            [],
            {Attributes.STATE: States.UNKNOWN, Attributes.VALUE: ""},
            device_class=DeviceClasses.CUSTOM,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({Attributes.STATE: States.UNAVAILABLE})
            return
        try:
            value = self._read(self._device)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.debug("Sensor %s read failed: %s", self.id, err)
            value = None
        if value is None:
            self.update({Attributes.STATE: States.UNKNOWN, Attributes.VALUE: ""})
        else:
            self.update({Attributes.STATE: States.ON, Attributes.VALUE: value})


def create_sensors(device_config: SportsConfig, device: SportsDevice) -> list[SportsSensor]:
    return [SportsSensor(device_config, device, key, label, read) for key, label, read in _SENSORS]
