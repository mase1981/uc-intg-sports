"""
Sports data model.

Plain immutable objects built from the ESPN responses. Nothing outside
espn.py needs to know the ESPN JSON layout.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PRE = "pre"
LIVE = "in"
POST = "post"


@dataclass(frozen=True)
class Team:
    id: str
    name: str  # "Arsenal", "Kansas City Chiefs"
    short: str  # "Arsenal", "Chiefs"
    abbr: str  # "ARS", "KC"
    color: str = ""  # hex without "#"
    alt_color: str = ""
    logo: str = ""  # default logo URL
    logo_dark: str = ""  # logo meant for dark backgrounds, if known


@dataclass(frozen=True)
class Side:
    team: Team
    score: str = ""
    shootout: str = ""  # penalty shoot-out goals
    winner: bool | None = None
    record: str = ""  # "4-0-1"
    form: str = ""  # "LWWWW"


@dataclass(frozen=True)
class Play:
    """A scoring play or card shown on the live and final cards."""

    team_id: str
    minute: str  # "67'"
    text: str  # "B. Saka"
    kind: str = "goal"  # goal, own_goal, penalty, red_card


@dataclass(frozen=True)
class Game:
    id: str
    start: datetime  # timezone aware (UTC)
    state: str  # PRE, LIVE or POST
    status: str  # ESPN status name, e.g. STATUS_FULL_TIME
    home: Side
    away: Side
    league_key: str = ""  # "soccer/eng.1"
    league_name: str = ""
    time_valid: bool = True  # False when the kick-off time is still TBD
    clock: str = ""  # "67'", "0:16"
    period: int = 0
    detail: str = ""  # ESPN short detail (only used for live and final labels)
    venue: str = ""
    city: str = ""
    broadcasts: tuple[str, ...] = ()
    plays: tuple[Play, ...] = ()
    situation: str = ""  # "3rd & 7 at KC 35", last play
    possession: str = ""  # team id with the ball (American football)
    outs: int | None = None  # baseball
    bases: tuple[bool, bool, bool] = (False, False, False)  # baseball: first, second, third
    count: str = ""  # baseball balls-strikes, "1-2"
    note: str = ""  # "Leg 2 of 2", "Aggregate 3-2"

    @property
    def is_live(self) -> bool:
        return self.state == LIVE

    @property
    def is_final(self) -> bool:
        return self.state == POST and not self.is_off

    @property
    def is_off(self) -> bool:
        """Postponed, cancelled, abandoned or suspended."""
        return any(word in self.status for word in ("POSTPONED", "CANCELED", "CANCELLED", "ABANDONED", "SUSPENDED"))

    def side_of(self, team_id: str) -> Side | None:
        if self.home.team.id == team_id:
            return self.home
        if self.away.team.id == team_id:
            return self.away
        return None

    def opponent_of(self, team_id: str) -> Side | None:
        if self.home.team.id == team_id:
            return self.away
        if self.away.team.id == team_id:
            return self.home
        return None


@dataclass(frozen=True)
class TeamInfo:
    team: Team
    standing: str = ""  # "2nd in English Premier League"
    record: str = ""  # "4-0-1"
    next_game: Game | None = None


@dataclass(frozen=True)
class TableRow:
    rank: int
    team: Team
    played: str = ""
    wins: str = ""
    draws: str = ""
    losses: str = ""
    diff: str = ""  # goal / point differential, "+8"
    points: str = ""
    pct: str = ""  # win percentage
    behind: str = ""  # games behind
    note_color: str = ""  # qualification colour, "#81D6AC"


@dataclass(frozen=True)
class TableGroup:
    name: str  # "Premier League", "AFC East"
    rows: tuple[TableRow, ...] = field(default_factory=tuple)
