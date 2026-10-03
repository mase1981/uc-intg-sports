"""
Sports select entities.

Everything can be changed from the Remote without running setup again:

  League / Team      pick another team to follow (the League select fills the Team select)
  Region             one tap for US style or international style
  Time Format        12-hour or 24-hour
  Date Format        "Sat, Oct 10" or "Sat 10 Oct"
  Matchup Order      "Home v Away" or "Away @ Home"
  Time Zone          the Remote's own zone or a fixed one
  League Card        scoreboard or table
  Text Size          Normal, Large or Extra Large artwork text

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ucapi import StatusCodes
from ucapi.select import Attributes, Commands, States
from ucapi_framework import SelectEntity

from uc_intg_sports.art import TEXT_LARGE, TEXT_NORMAL, TEXT_XLARGE
from uc_intg_sports.config import VIEW_SCORES, VIEW_TABLE, SportsConfig
from uc_intg_sports.device import SportsDevice
from uc_intg_sports.leagues import get_league, league_by_label, league_labels
from uc_intg_sports.model import Team
from uc_intg_sports.prefs import (
    AUTO_TZ,
    AWAY_FIRST,
    DATE_INTL,
    DATE_US,
    HOME_FIRST,
    REGION_INTL,
    REGION_US,
    TIME_12H,
    TIME_24H,
    TIME_ZONES,
)

_LOG = logging.getLogger(__name__)

AUTO_TZ_LABEL = "Remote's time zone"
REGION_OPTIONS = {
    "United States (12h, Oct 10, Away @ Home)": REGION_US,
    "International (24h, 10 Oct, Home v Away)": REGION_INTL,
}
CUSTOM = "Custom"
TIME_OPTIONS = {"12-hour (7:30 PM)": TIME_12H, "24-hour (19:30)": TIME_24H}
DATE_OPTIONS = {"Sat, Oct 10": DATE_US, "Sat 10 Oct": DATE_INTL}
MATCHUP_OPTIONS = {"Home v Away": HOME_FIRST, "Away @ Home": AWAY_FIRST}
VIEW_OPTIONS = {"Scores": VIEW_SCORES, "Table": VIEW_TABLE}
TEXT_OPTIONS = {"Normal": TEXT_NORMAL, "Large": TEXT_LARGE, "Extra Large": TEXT_XLARGE}


def team_labels(teams: list[Team]) -> dict[str, Team]:
    """Unique option labels; duplicate names get their abbreviation."""
    counts: dict[str, int] = {}
    for team in teams:
        counts[team.name] = counts.get(team.name, 0) + 1
    return {(f"{team.name} ({team.abbr})" if counts[team.name] > 1 else team.name): team for team in teams}


class SportsSelect(SelectEntity):
    """A select whose options and actions are supplied by small callables."""

    def __init__(
        self,
        device_config: SportsConfig,
        device: SportsDevice,
        key: str,
        label: str,
        options: Callable[[], list[str]],
        current: Callable[[], str],
        choose: Callable[[str], Any],
    ) -> None:
        self._device = device
        self._options = options
        self._current = current
        self._choose = choose
        super().__init__(
            f"select.{device_config.identifier}.{key}",
            f"{device_config.name} {label}",
            {Attributes.STATE: States.UNKNOWN, Attributes.OPTIONS: [], Attributes.CURRENT_OPTION: ""},
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        options = self._options()
        current = self._current()
        self.update(
            {
                Attributes.STATE: States.ON if options else States.UNAVAILABLE,
                Attributes.OPTIONS: options,
                Attributes.CURRENT_OPTION: current if current in options else "",
            }
        )

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        options = self._options()
        if not options:
            return StatusCodes.SERVICE_UNAVAILABLE
        current = self._current()
        index = options.index(current) if current in options else -1
        if cmd_id == Commands.SELECT_OPTION:
            option = (params or {}).get("option", "")
            if option not in options:
                return StatusCodes.BAD_REQUEST
        elif cmd_id == Commands.SELECT_FIRST:
            option = options[0]
        elif cmd_id == Commands.SELECT_LAST:
            option = options[-1]
        elif cmd_id == Commands.SELECT_NEXT:
            option = options[(index + 1) % len(options)]
        elif cmd_id == Commands.SELECT_PREVIOUS:
            option = options[(index - 1) % len(options)]
        else:
            return StatusCodes.NOT_IMPLEMENTED
        try:
            result = self._choose(option)
            if hasattr(result, "__await__"):
                await result
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Select %s failed: %s", self._device.log_id, self.id, err)
            return StatusCodes.SERVER_ERROR
        await self.sync_state()
        return StatusCodes.OK


def _label_for(options: dict[str, str], value: str) -> str:
    return next((label for label, option in options.items() if option == value), "")


def create_selects(device_config: SportsConfig, device: SportsDevice) -> list[SportsSelect]:
    cfg = device.config  # the live config object, updated by the device

    # League / Team -------------------------------------------------------
    def league_current() -> str:
        league = get_league(device.browse_league)
        return league.label if league else ""

    async def league_choose(option: str) -> None:
        league = league_by_label(option)
        if league is not None:
            await device.set_browse_league(league.key)

    def team_options() -> list[str]:
        teams = device.cached_teams(device.browse_league)
        if not teams:
            device.request_teams(device.browse_league)
        return list(team_labels(teams))

    def team_current() -> str:
        if device.browse_league != cfg.league:
            return ""
        labels = team_labels(device.cached_teams(device.browse_league))
        return next((label for label, team in labels.items() if team.id == cfg.team_id), "")

    async def team_choose(option: str) -> None:
        team = team_labels(device.cached_teams(device.browse_league)).get(option)
        if team is not None:
            await device.follow(device.browse_league, team)

    # Display preferences -------------------------------------------------
    def region_options() -> list[str]:
        options = list(REGION_OPTIONS)
        return options if device.region else options + [CUSTOM]

    def region_current() -> str:
        return _label_for(REGION_OPTIONS, device.region) or CUSTOM

    def region_choose(option: str) -> None:
        if option in REGION_OPTIONS:
            device.set_region(REGION_OPTIONS[option])

    def pref_select(key: str, label: str, options: dict[str, str]) -> SportsSelect:
        return SportsSelect(
            device_config, device, key, label,
            options=lambda: list(options),
            current=lambda: _label_for(options, getattr(cfg, key)),
            choose=lambda option: device.set_pref(key, options[option]),
        )

    tz_options = [AUTO_TZ_LABEL] + list(TIME_ZONES)

    def tz_current() -> str:
        return AUTO_TZ_LABEL if cfg.time_zone == AUTO_TZ else cfg.time_zone

    def tz_choose(option: str) -> None:
        device.set_pref("time_zone", AUTO_TZ if option == AUTO_TZ_LABEL else option)

    return [
        SportsSelect(device_config, device, "league", "League",
                     options=league_labels, current=league_current, choose=league_choose),
        SportsSelect(device_config, device, "team", "Team",
                     options=team_options, current=team_current, choose=team_choose),
        SportsSelect(device_config, device, "region", "Region",
                     options=region_options, current=region_current, choose=region_choose),
        pref_select("time_format", "Time Format", TIME_OPTIONS),
        pref_select("date_format", "Date Format", DATE_OPTIONS),
        pref_select("matchup", "Matchup Order", MATCHUP_OPTIONS),
        pref_select("text_size", "Text Size", TEXT_OPTIONS),
        SportsSelect(device_config, device, "time_zone", "Time Zone",
                     options=lambda: tz_options, current=tz_current, choose=tz_choose),
        SportsSelect(device_config, device, "card_view", "League Card",
                     options=lambda: list(VIEW_OPTIONS),
                     current=lambda: _label_for(VIEW_OPTIONS, device.card_view),
                     choose=lambda option: device.set_card_view(VIEW_OPTIONS[option])),
    ]

