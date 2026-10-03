"""
Sports setup flow.

Step 1: region style, league and time zone.
Step 2: team, loaded live from the chosen league.

Run setup again to follow more teams; each team gets its own tiles.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import Any

from ucapi import RequestUserInput, SetupError
from ucapi_framework import BaseSetupFlow

from uc_intg_sports.art import TEXT_LARGE, TEXT_NORMAL, TEXT_SIZES, TEXT_XLARGE
from uc_intg_sports.config import SportsConfig, build_identifier
from uc_intg_sports.espn import EspnClient, SportsDataError
from uc_intg_sports.leagues import LEAGUES, get_league
from uc_intg_sports.prefs import AUTO_TZ, REGION_INTL, REGION_US, REGIONS, TIME_ZONES
from uc_intg_sports.select import team_labels

_LOG = logging.getLogger(__name__)


def _label(text: str) -> dict[str, str]:
    return {"en": text}


def _dropdown(field_id: str, label: str, value: str, items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "id": field_id,
        "label": _label(label),
        "field": {"dropdown": {"value": value, "items": [{"id": i, "label": _label(t)} for i, t in items]}},
    }


def _info(field_id: str, text: str) -> dict[str, Any]:
    return {"id": field_id, "label": _label(""), "field": {"label": {"value": _label(text)}}}


class SportsSetupFlow(BaseSetupFlow[SportsConfig]):
    """Two-step setup: league, then team."""

    _step1: dict[str, str] | None = None
    _team_ids: dict[str, str] | None = None

    def get_manual_entry_form(self) -> RequestUserInput:
        self._step1 = None
        return self._league_form()

    def _league_form(self, error: str = "") -> RequestUserInput:
        settings: list[dict[str, Any]] = []
        if error:
            settings.append(_info("error", f"⚠️ {error}"))
        settings.append(
            _dropdown(
                "region", "Display style", REGION_US,
                [(REGION_US, "United States - 12-hour, Oct 10, Away @ Home"),
                 (REGION_INTL, "International - 24-hour, 10 Oct, Home v Away")],
            )
        )
        settings.append(
            _dropdown("league", "League", "soccer/eng.1", [(league.key, league.label) for league in LEAGUES.values()])
        )
        settings.append(
            _dropdown("time_zone", "Time zone", AUTO_TZ,
                      [(AUTO_TZ, "Remote's time zone (recommended)")] + [(zone, zone) for zone in TIME_ZONES])
        )
        settings.append(
            _dropdown("text_size", "Artwork text size", TEXT_NORMAL,
                      [(TEXT_NORMAL, "Normal (most detail)"), (TEXT_LARGE, "Large"),
                       (TEXT_XLARGE, "Extra Large (easiest to read from the couch)")])
        )
        settings.append(_info("hint", "All of these can be changed later from the Remote with the select entities."))
        return RequestUserInput(_label("Sports - League"), settings)

    def _team_form(self, league_name: str, labels: list[str], error: str = "") -> RequestUserInput:
        settings: list[dict[str, Any]] = []
        if error:
            settings.append(_info("error", f"⚠️ {error}"))
        settings.append(_dropdown("team", f"Team ({league_name})", labels[0], [(label, label) for label in labels]))
        settings.append(
            {"id": "name", "label": _label("Display name (optional)"), "field": {"text": {"value": ""}}}
        )
        return RequestUserInput(_label("Sports - Team"), settings)

    async def query_device(self, input_values: dict[str, Any]) -> SportsConfig | SetupError | RequestUserInput:
        if "team" not in input_values or self._step1 is None:
            return await self._handle_league_step(input_values)
        return self._handle_team_step(input_values)

    async def _handle_league_step(self, input_values: dict[str, Any]) -> RequestUserInput:
        region = str(input_values.get("region", REGION_US))
        league = get_league(str(input_values.get("league", "")))
        time_zone = str(input_values.get("time_zone", AUTO_TZ))
        text_size = str(input_values.get("text_size", TEXT_NORMAL))
        if text_size not in TEXT_SIZES:
            text_size = TEXT_NORMAL
        if region not in REGIONS:
            region = REGION_US
        if time_zone != AUTO_TZ and time_zone not in TIME_ZONES:
            time_zone = AUTO_TZ
        if league is None:
            return self._league_form("Please choose a league.")

        client = EspnClient()
        try:
            teams = await client.teams(league)
        except SportsDataError as err:
            _LOG.error("Loading teams for %s failed: %s", league.key, err)
            return self._league_form("Could not reach ESPN to load the teams. Check the Remote's internet "
                                     "connection and try again.")
        finally:
            await client.close()

        labels = team_labels(teams)
        self._team_ids = {label: f"{team.id}|{team.name}|{team.abbr}" for label, team in labels.items()}
        self._step1 = {"region": region, "league": league.key, "time_zone": time_zone, "text_size": text_size}
        return self._team_form(league.label, list(labels))

    def _handle_team_step(self, input_values: dict[str, Any]) -> SportsConfig | RequestUserInput:
        step1 = self._step1 or {}
        league = get_league(step1.get("league", ""))
        picked = (self._team_ids or {}).get(str(input_values.get("team", "")))
        if league is None or picked is None:
            self._step1 = None
            return self._league_form("Please choose the league again.")
        team_id, team_name, team_abbr = (picked.split("|", 2) + ["", ""])[:3]
        time_format, date_format, matchup = REGIONS[step1["region"]]
        name = str(input_values.get("name", "")).strip() or team_name
        self._step1 = None
        return SportsConfig(
            identifier=build_identifier(league.key, team_id),
            name=name,
            league=league.key,
            team_id=team_id,
            team_name=team_name,
            team_abbr=team_abbr,
            region=step1["region"],
            time_format=time_format,
            date_format=date_format,
            matchup=matchup,
            time_zone=step1["time_zone"],
            text_size=step1.get("text_size", TEXT_NORMAL),
        )
