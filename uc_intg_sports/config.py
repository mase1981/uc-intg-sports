"""
Sports configuration.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ucapi_framework import BaseConfigManager

from uc_intg_sports.prefs import AUTO_TZ, DATE_INTL, HOME_FIRST, REGION_INTL, TIME_24H, Prefs

VIEW_SCORES = "scores"
VIEW_TABLE = "table"


def build_identifier(league_key: str, team_id: str) -> str:
    """Stable, dot-free identifier, e.g. "sports_soccer_eng_1_359"."""
    return "sports_" + re.sub(r"[^a-z0-9]+", "_", f"{league_key}_{team_id}".lower()).strip("_")


@dataclass
class SportsConfig:
    """One followed team."""

    identifier: str
    name: str
    league: str  # "soccer/eng.1"
    team_id: str
    team_name: str = ""
    team_abbr: str = ""
    region: str = REGION_INTL
    time_format: str = TIME_24H
    date_format: str = DATE_INTL
    matchup: str = HOME_FIRST
    time_zone: str = AUTO_TZ
    card_view: str = VIEW_SCORES
    text_size: str = "normal"  # "normal", "large" or "xlarge"

    @property
    def prefs(self) -> Prefs:
        return Prefs(self.time_format, self.date_format, self.matchup, self.time_zone)


class SportsConfigManager(BaseConfigManager[SportsConfig]):
    """Configuration manager with automatic JSON persistence."""
