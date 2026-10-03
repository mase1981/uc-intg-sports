"""
ESPN data client.

The only module that knows ESPN URLs and JSON. ESPN's public site API is
unofficial, so every field is read defensively: a missing or renamed field
leaves that value empty instead of raising. Network and HTTP failures raise
SportsDataError so the caller can keep its last good data.

Endpoints (all verified 2026-10-03):
  site/v2/sports/{sport}/{league}/scoreboard
  site/v2/sports/{sport}/{league}/teams?limit=1000
  site/v2/sports/{sport}/{league}/teams/{id}            (team, nextEvent, standing)
  site/v2/sports/{sport}/{league}/teams/{id}/schedule   (results; "?fixture=true" = soccer fixtures)
  v2/sports/{sport}/{league}/standings
Soccer team and schedule calls use league "all" so cups and European games are included.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
import ssl
from datetime import datetime, timezone
from typing import Any

import aiohttp
import certifi

from uc_intg_sports.leagues import League
from uc_intg_sports.model import LIVE, POST, PRE, Game, Play, Side, TableGroup, TableRow, Team, TeamInfo

_LOG = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports"
STANDINGS = "https://site.api.espn.com/apis/v2/sports"
_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=10)
_HEADERS = {"User-Agent": "uc-intg-sports", "Accept": "application/json"}


def _ssl_context() -> ssl.SSLContext:
    """The Remote has no system CA certificates; use certifi's bundle."""
    return ssl.create_default_context(cafile=certifi.where())


class SportsDataError(Exception):
    """ESPN could not be reached or returned an error."""


# ----------------------------------------------------------------------
# Safe readers
# ----------------------------------------------------------------------
def _get(data: Any, *path: Any, default: Any = None) -> Any:
    """Walk dicts and lists; return default on any missing step."""
    for step in path:
        try:
            data = data[step]
        except (KeyError, IndexError, TypeError):
            return default
    return default if data is None else data


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _list(data: Any, *path: Any) -> list:
    """Like _get, but only ever returns a list."""
    value = _get(data, *path, default=[])
    return value if isinstance(value, list) else []


def _text(data: Any, *path: Any) -> str:
    value = _get(data, *path, default="")
    return value.strip() if isinstance(value, str) else str(value) if isinstance(value, (int, float)) else ""


def _score(value: Any) -> str:
    """Scores come as "2", 2 or {"value": 2, "displayValue": "2"}."""
    if isinstance(value, dict):
        value = value.get("displayValue", value.get("value"))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _time(value: Any) -> datetime | None:
    """ESPN dates look like "2026-10-10T11:30Z" or "2026-10-10T11:30:00Z"."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _logos(team: dict) -> tuple[str, str]:
    """Return (default logo, dark-background logo)."""
    default = _text(team, "logo")
    dark = ""
    for logo in _list(team, "logos"):
        rel = _list(logo, "rel")
        href = _text(logo, "href")
        if not href:
            continue
        if "dark" in rel and not dark:
            dark = href
        elif "default" in rel and not default:
            default = href
    if default and not dark and "/500/" in default:
        dark = default.replace("/500/", "/500-dark/")  # ESPN convention, verified for soccer
    return default, dark


def parse_team(team: Any) -> Team | None:
    if not isinstance(team, dict) or not _text(team, "id"):
        return None
    name = _text(team, "displayName") or _text(team, "name") or _text(team, "location")
    logo, dark = _logos(team)
    return Team(
        id=_text(team, "id"),
        name=name,
        short=_text(team, "shortDisplayName") or _text(team, "name") or name,
        abbr=_text(team, "abbreviation") or name[:3].upper(),
        color=_text(team, "color").lstrip("#"),
        alt_color=_text(team, "alternateColor").lstrip("#"),
        logo=logo,
        logo_dark=dark,
    )


def _side(competitor: Any) -> Side | None:
    team = parse_team(_get(competitor, "team"))
    if team is None:
        return None
    record = ""
    for item in _list(competitor, "records") or _list(competitor, "record"):
        if _text(item, "type") in ("total", "") and _text(item, "summary"):
            record = _text(item, "summary")
            break
    winner = _get(competitor, "winner")
    return Side(
        team=team,
        score=_score(_get(competitor, "score")),
        shootout=_score(_get(competitor, "shootoutScore")),
        winner=winner if isinstance(winner, bool) else None,
        record=record,
        form=_text(competitor, "form"),
    )


def _plays(competition: Any) -> tuple[Play, ...]:
    plays = []
    for detail in _list(competition, "details"):
        red = bool(_get(detail, "redCard", default=False))
        if not (_get(detail, "scoringPlay", default=False) or red):
            continue
        if _get(detail, "shootout", default=False):
            continue
        kind = "red_card" if red else "own_goal" if _get(detail, "ownGoal", default=False) else (
            "penalty" if _get(detail, "penaltyKick", default=False) else "goal"
        )
        player = _get(detail, "athletesInvolved", 0, default={})
        plays.append(
            Play(
                team_id=_text(detail, "team", "id"),
                minute=_text(detail, "clock", "displayValue"),
                text=_text(player, "shortName") or _text(player, "displayName") or _text(detail, "type", "text"),
                kind=kind,
            )
        )
    return tuple(plays)


def _broadcasts(competition: Any) -> tuple[str, ...]:
    names: list[str] = []
    for item in _list(competition, "broadcasts"):
        names.extend(name for name in _list(item, "names") if isinstance(name, str))
    for item in _list(competition, "geoBroadcasts"):
        name = _text(item, "media", "shortName")
        if name:
            names.append(name)
    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return tuple(unique[:3])


def parse_game(event: Any, league: League | None = None) -> Game | None:
    """Build a Game from a scoreboard, schedule or nextEvent entry."""
    competition = _get(event, "competitions", 0)
    if not isinstance(competition, dict):
        return None
    start = _time(_get(event, "date")) or _time(_get(competition, "date"))
    sides = {_text(c, "homeAway"): _side(c) for c in _list(competition, "competitors")}
    home, away = sides.get("home"), sides.get("away")
    if start is None or home is None or away is None:
        return None

    status = _get(competition, "status")
    if not isinstance(status, dict):
        status = _get(event, "status")
    if not isinstance(status, dict):
        status = {}
    state = _text(status, "type", "state")
    if state not in (PRE, LIVE, POST):
        state = PRE

    event_league = _get(event, "league", default={})
    if not isinstance(event_league, dict):
        event_league = {}
    league_slug = _text(event_league, "slug")
    if league_slug and league is not None:
        league_key = f"{league.sport}/{league_slug}"
    else:
        league_key = league.key if league is not None else ""
    league_name = _text(event_league, "shortName") or _text(event_league, "abbreviation") or _text(event_league, "name")
    if not league_name and league is not None and league_key == league.key:
        league_name = league.name

    situation = _get(competition, "situation", default={})
    if not isinstance(situation, dict):
        situation = {}
    situation_text = _text(situation, "downDistanceText") or _text(situation, "lastPlay", "text")
    outs = _get(situation, "outs")
    balls, strikes = _get(situation, "balls"), _get(situation, "strikes")

    notes = [_text(note, "headline") for note in _list(competition, "notes")]
    return Game(
        id=_text(event, "id") or _text(competition, "id"),
        start=start,
        state=state,
        status=_text(status, "type", "name"),
        home=home,
        away=away,
        league_key=league_key,
        league_name=league_name,
        time_valid=_get(competition, "timeValid", default=_get(event, "timeValid", default=True)) is not False,
        clock=_text(status, "displayClock"),
        period=_int(_get(status, "period")),
        detail=_text(status, "type", "shortDetail"),
        venue=_text(competition, "venue", "fullName"),
        city=_text(competition, "venue", "address", "city"),
        broadcasts=_broadcasts(competition),
        plays=_plays(competition),
        situation=situation_text,
        possession=_text(situation, "possession"),
        outs=outs if isinstance(outs, int) else None,
        bases=(
            bool(_get(situation, "onFirst", default=False)),
            bool(_get(situation, "onSecond", default=False)),
            bool(_get(situation, "onThird", default=False)),
        ),
        count=f"{balls}-{strikes}" if isinstance(balls, int) and isinstance(strikes, int) else "",
        note=next((note for note in notes if note), ""),
    )


def parse_games(data: Any, league: League | None = None) -> list[Game]:
    games = []
    for event in _list(data, "events"):
        try:
            game = parse_game(event, league)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.debug("Skipping unreadable event: %s", err)
            game = None
        if game is not None:
            games.append(game)
    return games


def _stat(entry: Any, *names: str) -> str:
    for stat in _list(entry, "stats"):
        if _text(stat, "name") in names or _text(stat, "abbreviation") in names:
            return _text(stat, "displayValue")
    return ""


def parse_standings(data: Any) -> list[TableGroup]:
    """Flatten the standings tree into groups that hold entries."""
    groups: list[TableGroup] = []

    def walk(node: Any) -> None:
        entries = _list(node, "standings", "entries")
        if entries:
            rows = []
            for index, entry in enumerate(entries):
                team = parse_team(_get(entry, "team"))
                if team is None:
                    continue
                rank = _stat(entry, "rank", "playoffSeed")
                rows.append(
                    TableRow(
                        rank=int(rank) if rank.isdigit() else index + 1,
                        team=team,
                        played=_stat(entry, "gamesPlayed"),
                        wins=_stat(entry, "wins"),
                        draws=_stat(entry, "ties"),
                        losses=_stat(entry, "losses"),
                        diff=_stat(entry, "pointDifferential", "differential"),
                        points=_stat(entry, "points"),
                        pct=_stat(entry, "winPercent"),
                        behind=_stat(entry, "gamesBehind"),
                        note_color=_text(entry, "note", "color"),
                    )
                )
            rows.sort(key=lambda row: row.rank)
            groups.append(TableGroup(name=_text(node, "name") or _text(node, "abbreviation"), rows=tuple(rows)))
        for child in _list(node, "children"):
            walk(child)

    walk(data)
    return groups


# ----------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------
class EspnClient:
    """Small async client for the ESPN site API."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    def _ensure_session(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_TIMEOUT, headers=_HEADERS, connector=aiohttp.TCPConnector(ssl=_ssl_context())
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _json(self, url: str, params: dict[str, str] | None = None) -> Any:
        self._ensure_session()
        try:
            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    raise SportsDataError(f"HTTP {response.status} for {url}")
                return await response.json(content_type=None)
        except SportsDataError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SportsDataError(f"{type(err).__name__} for {url}: {err}") from err

    async def fetch_bytes(self, url: str) -> bytes:
        """Download a logo or other image."""
        self._ensure_session()
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    raise SportsDataError(f"HTTP {response.status} for {url}")
                return await response.read()
        except SportsDataError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SportsDataError(f"{type(err).__name__} for {url}: {err}") from err

    @staticmethod
    def _team_path(league: League) -> str:
        # Soccer clubs play in several competitions; "all" returns every one of them.
        return f"{SITE}/{league.sport}/all" if league.is_soccer else f"{SITE}/{league.sport}/{league.slug}"

    async def teams(self, league: League) -> list[Team]:
        data = await self._json(f"{SITE}/{league.sport}/{league.slug}/teams", {"limit": "1000"})
        teams = [parse_team(_get(item, "team")) for item in _list(data, "sports", 0, "leagues", 0, "teams")]
        result = [team for team in teams if team is not None]
        if not result:
            raise SportsDataError(f"No teams returned for {league.key}")
        return sorted(result, key=lambda team: team.name.lower())

    async def team(self, league: League, team_id: str) -> TeamInfo:
        try:
            data = await self._json(f"{self._team_path(league)}/teams/{team_id}")
        except SportsDataError:
            if not league.is_soccer:
                raise
            data = await self._json(f"{SITE}/{league.sport}/{league.slug}/teams/{team_id}")
        raw = _get(data, "team", default={})
        team = parse_team(raw)
        if team is None:
            raise SportsDataError(f"Team {team_id} not found in {league.key}")
        next_events = _list(raw, "nextEvent")
        return TeamInfo(
            team=team,
            standing=_text(raw, "standingSummary"),
            record=_text(raw, "record", "items", 0, "summary"),
            next_game=parse_game(next_events[0], league) if next_events else None,
        )

    async def schedule(
        self, league: League, team_id: str, fixtures: bool = False, season_type: int | None = None
    ) -> list[Game]:
        """Results (fixtures=False) or upcoming soccer fixtures (fixtures=True).

        For other sports the schedule holds both played and upcoming games of the
        current season part; season_type (2 = regular season) asks for another part.
        """
        params: dict[str, str] | None = {"fixture": "true"} if fixtures else None
        if season_type is not None:
            params = {**(params or {}), "seasontype": str(season_type)}
        try:
            data = await self._json(f"{self._team_path(league)}/teams/{team_id}/schedule", params)
        except SportsDataError:
            if not league.is_soccer:
                raise
            data = await self._json(f"{SITE}/{league.sport}/{league.slug}/teams/{team_id}/schedule", params)
        return parse_games(data, league)

    async def scoreboard(self, league: League, day: str | None = None) -> tuple[list[Game], str]:
        """Games on ESPN's current scoreboard (or one day, "YYYYMMDD") and the league logo."""
        params = {"limit": "100"}
        if day:
            params["dates"] = day
        data = await self._json(f"{SITE}/{league.sport}/{league.slug}/scoreboard", params)
        logo = ""
        for item in _list(data, "leagues", 0, "logos"):
            rel = _list(item, "rel")
            if "dark" in rel:
                logo = _text(item, "href")
                break
            logo = logo or _text(item, "href")
        return parse_games(data, league), logo

    async def standings(self, league: League) -> list[TableGroup]:
        """League tables; empty for cups and tournaments that have none."""
        data = await self._json(f"{STANDINGS}/{league.sport}/{league.slug}/standings")
        return parse_standings(data)
