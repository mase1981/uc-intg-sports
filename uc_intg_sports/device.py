"""
Sports device: one followed team.

A PollingDevice that ticks every 30 seconds while its entities are shown on
the Remote (the framework stops it in standby). Each tick decides which ESPN
requests are due:

  team info and standing    every 6 hours
  schedule                  hourly, every 10 minutes close to a game
  league scoreboard         every 15 minutes, every minute while a game is live
  league table              every 6 hours and right after a followed game ends
  live game                 every 30 seconds from 10 minutes before kick-off until it ends

A failed request is retried with a growing delay and the last good data stays
on screen. Nothing here raises into the framework.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from PIL import Image
from ucapi_framework import PollingDevice

from uc_intg_sports import logos as logo_store
from uc_intg_sports.art import TEXT_NORMAL, TEXT_SIZES
from uc_intg_sports.config import VIEW_SCORES, VIEW_TABLE, SportsConfig
from uc_intg_sports.espn import EspnClient, SportsDataError
from uc_intg_sports.leagues import League, get_league
from uc_intg_sports.model import Game, TableGroup, Team, TeamInfo
from uc_intg_sports.prefs import (
    AUTO_TZ,
    AWAY_FIRST,
    DATE_INTL,
    DATE_US,
    HOME_FIRST,
    REGIONS,
    TIME_12H,
    TIME_24H,
    TIME_ZONES,
)

_LOG = logging.getLogger(__name__)

_TICK = 30
_HOUR = 3600
_INTERVALS = {"team": 6 * _HOUR, "schedule": _HOUR, "scores": 15 * 60, "table": 6 * _HOUR}
_PRE_LIVE = timedelta(minutes=10)  # start live polling this long before kick-off
_MAX_GAME = timedelta(hours=5)  # stop live polling this long after kick-off at the latest
_RECENT = timedelta(hours=14)  # a result counts as "just played" for this long after kick-off
_TEAMS_TTL = 24 * _HOUR

_PREF_VALUES = {
    "time_format": (TIME_12H, TIME_24H),
    "date_format": (DATE_US, DATE_INTL),
    "matchup": (AWAY_FIRST, HOME_FIRST),
    "text_size": TEXT_SIZES,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SportsDevice(PollingDevice):
    """Polling device following one team."""

    def __init__(self, device_config: SportsConfig, **kwargs: Any) -> None:
        super().__init__(device_config, poll_interval=_TICK, **kwargs)
        self._device_config = device_config
        self._client = EspnClient()
        self._connect_lock = asyncio.Lock()
        self._update_lock = asyncio.Lock()
        self._state = "UNAVAILABLE"

        self._info: TeamInfo | None = None
        self._fixtures: list[Game] = []
        self._results: list[Game] = []
        self._live: dict[str, Game] = {}
        self._scores: list[Game] = []
        self._league_logo = ""
        self._table: list[TableGroup] = []
        self._teams: dict[str, tuple[float, list[Team]]] = {}
        self._teams_tried: dict[str, float] = {}
        self._teams_task: asyncio.Task | None = None
        self._prefetch_task: asyncio.Task | None = None
        self._directory: dict[str, Team] = {}  # team id -> most complete team details seen

        self._due: dict[str, float] = {}
        self._fails: dict[str, int] = {}
        self._fail_since: dict[str, float] = {}
        self.browse_league = device_config.league  # league shown in the Team select

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    @property
    def identifier(self) -> str:
        return self._device_config.identifier

    @property
    def name(self) -> str:
        return self._device_config.name

    @property
    def address(self) -> str | None:
        return None

    @property
    def log_id(self) -> str:
        return self._device_config.name

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------------
    # Read access for entities
    # ------------------------------------------------------------------
    @property
    def config(self) -> SportsConfig:
        return self._device_config

    @property
    def prefs(self):
        return self._device_config.prefs

    @property
    def league(self) -> League:
        return get_league(self._device_config.league) or League(self._device_config.league, "", "")

    @property
    def team_id(self) -> str:
        return self._device_config.team_id

    @property
    def team(self) -> Team:
        if self._info is not None:
            return self._info.team
        cfg = self._device_config
        return Team(cfg.team_id, cfg.team_name or cfg.name, cfg.team_name or cfg.name, cfg.team_abbr or "")

    @property
    def info(self) -> TeamInfo | None:
        return self._info

    @property
    def has_data(self) -> bool:
        return self._info is not None or bool(self._fixtures) or bool(self._results)

    @property
    def scores(self) -> list[Game]:
        return [self._enrich(self._live.get(game.id, game)) for game in self._scores]

    @property
    def league_logo(self) -> str:
        return self._league_logo

    @property
    def table(self) -> list[TableGroup]:
        return self._table

    @property
    def text_size(self) -> str:
        size = self._device_config.text_size
        return size if size in TEXT_SIZES else TEXT_NORMAL

    @property
    def card_view(self) -> str:
        return VIEW_TABLE if self._device_config.card_view == VIEW_TABLE else VIEW_SCORES

    def _merged(self, game: Game) -> Game:
        """Best version of a game: live data, else the scoreboard entry, else the schedule entry."""
        best = self._live.get(game.id)
        if best is None:
            best = next((g for g in self._scores if g.id == game.id), game)
        return self._enrich(best)

    # Schedules leave out team colours, records and TV; fill them from what else was loaded.
    def _learn(self, teams: list[Team]) -> None:
        for team in teams:
            known = self._directory.get(team.id)
            if known is None:
                self._directory[team.id] = team
                continue
            merged = {f.name: getattr(team, f.name) or getattr(known, f.name) for f in dataclasses.fields(Team)}
            self._directory[team.id] = Team(**merged)

    def rich_team(self, team: Team) -> Team:
        known = self._directory.get(team.id)
        if known is None or (team.color and team.logo):
            return team
        return Team(**{f.name: getattr(team, f.name) or getattr(known, f.name) for f in dataclasses.fields(Team)})

    def _enrich(self, game: Game) -> Game:
        home = dataclasses.replace(game.home, team=self.rich_team(game.home.team))
        away = dataclasses.replace(game.away, team=self.rich_team(game.away.team))
        return dataclasses.replace(game, home=home, away=away)

    def timeline(self) -> list[Game]:
        """Recent results, any live game and upcoming games, oldest first."""
        games: dict[str, Game] = {}
        for game in self._results[:5] + self._fixtures[:10]:
            games[game.id] = self._merged(game)
        for game in self._live.values():
            if game.side_of(self.team_id) is not None:
                games[game.id] = game
        return sorted(games.values(), key=lambda game: game.start)

    def focus(self, games: list[Game]) -> int:
        """Index of the game to show by default: live, just played, else next."""
        if not games:
            return 0
        now = _utcnow()
        for index, game in enumerate(games):
            if game.is_live:
                return index
        recent = [i for i, game in enumerate(games) if game.state == "post" and now - game.start <= _RECENT]
        if recent:
            return recent[-1]
        upcoming = [i for i, game in enumerate(games) if game.state == "pre" and game.start >= now - _PRE_LIVE]
        if upcoming:
            return upcoming[0]
        return len(games) - 1

    def current_game(self) -> Game | None:
        games = self.timeline()
        return games[self.focus(games)] if games else None

    def next_game(self) -> Game | None:
        now = _utcnow()
        for game in self.timeline():
            if game.state == "pre" and not game.is_off and game.start >= now - _PRE_LIVE:
                return game
        if self._info is not None and self._info.next_game is not None and self._info.next_game.state == "pre":
            return self._merged(self._info.next_game)
        return None

    def last_result(self) -> Game | None:
        results = [game for game in self.timeline() if game.is_final]
        return results[-1] if results else None

    def live_game(self) -> Game | None:
        return next((game for game in self.timeline() if game.is_live), None)

    def stale(self, *tasks: str) -> bool:
        """True when one of the tasks has been failing for longer than it should."""
        now = time.monotonic()
        for task in tasks or ("schedule", "live"):
            since = self._fail_since.get(task)
            if since is None:
                continue
            if not self.has_data and self._fails.get(task, 0) >= 2:
                return True  # nothing to show yet: say so instead of "Loading…"
            limit = 120 if task in ("live", "scores") else 3 * _HOUR
            if now - since > limit:
                return True
        return False

    async def logos(self, urls: list[str]) -> dict[str, Image.Image]:
        return await logo_store.get_logos(self._client, urls)

    async def team_logo(self, team: Team) -> tuple[str, Image.Image | None]:
        return await logo_store.get_team_logo(self._client, team.logo_dark, team.logo)

    async def teams_for(self, league_key: str) -> list[Team]:
        """Teams of a league for the Team select (cached for a day)."""
        cached = self._teams.get(league_key)
        if cached and time.monotonic() - cached[0] < _TEAMS_TTL:
            return cached[1]
        league = get_league(league_key)
        if league is None:
            return []
        try:
            teams = await self._client.teams(league)
        except SportsDataError as err:
            _LOG.warning("[%s] Could not load teams for %s: %s", self.log_id, league_key, err)
            return cached[1] if cached else []
        self._teams[league_key] = (time.monotonic(), teams)
        self._learn(teams)
        return teams

    def cached_teams(self, league_key: str) -> list[Team]:
        cached = self._teams.get(league_key)
        return cached[1] if cached else []

    def request_teams(self, league_key: str) -> None:
        """Load a league's teams in the background (at most every 5 minutes per league)."""
        if self._teams_task is not None and not self._teams_task.done():
            return
        if time.monotonic() - self._teams_tried.get(league_key, -300) < 300:
            return
        self._teams_tried[league_key] = time.monotonic()

        async def load() -> None:
            if await self.teams_for(league_key):
                self.push_update()

        try:
            self._teams_task = asyncio.get_running_loop().create_task(load())
        except RuntimeError:  # no running loop (tests)
            self._teams_task = None

    # ------------------------------------------------------------------
    # Changes from the selects
    # ------------------------------------------------------------------
    async def follow(self, league_key: str, team: Team) -> None:
        """Switch to another team, keep the display preferences."""
        if get_league(league_key) is None:
            return
        if league_key == self._device_config.league and team.id == self.team_id:
            return
        self.update_config(league=league_key, team_id=team.id, team_name=team.name, team_abbr=team.abbr)
        _LOG.info("[%s] Now following %s (%s)", self.log_id, team.name, league_key)
        self.browse_league = league_key
        self._info = None
        self._fixtures, self._results, self._scores, self._table = [], [], [], []
        self._live.clear()
        self._league_logo = ""
        self._due.clear()
        self._fails.clear()
        self._fail_since.clear()
        await self.refresh()

    async def set_browse_league(self, league_key: str) -> None:
        if get_league(league_key) is None:
            return
        self.browse_league = league_key
        await self.teams_for(league_key)
        self.push_update()

    def set_pref(self, key: str, value: str) -> None:
        if key in _PREF_VALUES and value not in _PREF_VALUES[key]:
            return
        if key == "time_zone" and value != AUTO_TZ and value not in TIME_ZONES:
            return
        if key not in _PREF_VALUES and key != "time_zone":
            return
        if getattr(self._device_config, key) == value:
            return
        changes = {key: value}
        if key in ("time_format", "date_format", "matchup"):
            changes["region"] = self._region_for({**self._pref_dict(), key: value})
        self.update_config(**changes)
        self.push_update()

    def set_region(self, region: str) -> None:
        if region not in REGIONS:
            return
        time_format, date_format, matchup = REGIONS[region]
        self.update_config(region=region, time_format=time_format, date_format=date_format, matchup=matchup)
        self.push_update()

    def set_card_view(self, view: str) -> None:
        if view not in (VIEW_SCORES, VIEW_TABLE) or view == self._device_config.card_view:
            return
        self.update_config(card_view=view)
        if view == VIEW_TABLE and not self._table:
            self._due["table"] = 0
        self.push_update()

    @property
    def region(self) -> str:
        """"us" or "intl" when the preferences match a preset, else ""."""
        return self._region_for(self._pref_dict())

    def _pref_dict(self) -> dict[str, str]:
        cfg = self._device_config
        return {"time_format": cfg.time_format, "date_format": cfg.date_format, "matchup": cfg.matchup}

    @staticmethod
    def _region_for(values: dict[str, str]) -> str:
        for region, (time_format, date_format, matchup) in REGIONS.items():
            if (values["time_format"], values["date_format"], values["matchup"]) == (time_format, date_format, matchup):
                return region
        return ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> bool:
        async with self._connect_lock:
            return await super().connect()

    async def establish_connection(self) -> None:
        """Start polling. Never raises: ESPN being down must not make the tiles unavailable."""
        self._state = "ON"
        await self._update()
        self.request_teams(self.browse_league)

    async def poll_device(self) -> None:
        await self._update()
        self.push_update()

    async def disconnect(self) -> None:
        async with self._connect_lock:
            await self._client.close()
        self._state = "UNAVAILABLE"
        await super().disconnect()

    async def refresh(self) -> None:
        """Fetch everything now (Refresh button, team change)."""
        for task in ("team", "schedule", "scores", "table"):
            self._due[task] = 0
        await self._update()
        self.push_update()

    # ------------------------------------------------------------------
    # Update scheduling
    # ------------------------------------------------------------------
    def _is_due(self, task: str) -> bool:
        return time.monotonic() >= self._due.get(task, 0)

    def _succeeded(self, task: str, interval: float) -> None:
        self._fails[task] = 0
        self._fail_since.pop(task, None)
        self._due[task] = time.monotonic() + interval

    def _failed(self, task: str, err: Exception, base: float = 60, cap: float = 1800) -> None:
        fails = self._fails.get(task, 0) + 1
        self._fails[task] = fails
        self._fail_since.setdefault(task, time.monotonic())
        delay = min(base * 2 ** (fails - 1), cap)
        self._due[task] = time.monotonic() + delay
        log = _LOG.warning if fails in (1, 5) else _LOG.debug
        log("[%s] %s update failed (%d in a row, retry in %ds): %s", self.log_id, task, fails, delay, err)

    def _active_game(self) -> Game | None:
        """The followed game that is live or about to start, if any."""
        now = _utcnow()
        for game in self.timeline():
            if game.is_live:
                return game
            if game.state == "pre" and game.time_valid and not game.is_off and \
                    game.start - _PRE_LIVE <= now <= game.start + _MAX_GAME:
                return game
        return None

    async def _update(self) -> None:
        async with self._update_lock:
            league = self.league
            for task, runner in (("team", self._update_team), ("schedule", self._update_schedule)):
                if self._is_due(task):
                    try:
                        await runner(league)
                    except SportsDataError as err:
                        self._failed(task, err)
                    except Exception as err:  # pylint: disable=broad-exception-caught
                        _LOG.exception("[%s] Unexpected %s error", self.log_id, task)
                        self._failed(task, err)

            active = self._active_game()
            if active is not None and self._is_due("live"):
                try:
                    await self._update_live(active)
                except SportsDataError as err:
                    self._failed("live", err, base=_TICK, cap=300)
                except Exception as err:  # pylint: disable=broad-exception-caught
                    _LOG.exception("[%s] Unexpected live error", self.log_id)
                    self._failed("live", err, base=_TICK, cap=300)

            for task, runner in (("scores", self._update_scores), ("table", self._update_table)):
                if self._is_due(task):
                    try:
                        await runner(league)
                    except SportsDataError as err:
                        self._failed(task, err, base=120, cap=3600)
                    except Exception as err:  # pylint: disable=broad-exception-caught
                        _LOG.exception("[%s] Unexpected %s error", self.log_id, task)
                        self._failed(task, err, base=120, cap=3600)

    async def _update_team(self, league: League) -> None:
        self._info = await self._client.team(league, self.team_id)
        self._learn([self._info.team])
        self._succeeded("team", _INTERVALS["team"])

    async def _update_schedule(self, league: League) -> None:
        now = _utcnow()
        if league.is_soccer:
            results = await self._client.schedule(league, self.team_id)
            try:
                fixtures = await self._client.schedule(league, self.team_id, fixtures=True)
            except SportsDataError as err:
                _LOG.debug("[%s] Fixtures unavailable, keeping previous: %s", self.log_id, err)
                fixtures = self._fixtures
            games = results + fixtures
        else:
            games = await self._client.schedule(league, self.team_id)
            if sum(1 for game in games if game.state == "pre" and game.start > now) < 2:
                # Between season parts (e.g. preseason) the default schedule can be short.
                try:
                    games += await self._client.schedule(league, self.team_id, season_type=2)
                except SportsDataError as err:
                    _LOG.debug("[%s] Regular season schedule unavailable: %s", self.log_id, err)

        unique = {game.id: game for game in games if game.side_of(self.team_id) is not None}
        self._results = sorted((g for g in unique.values() if g.state == "post"), key=lambda g: g.start, reverse=True)
        self._fixtures = sorted(
            (g for g in unique.values() if g.state != "post" and g.start >= now - _MAX_GAME), key=lambda g: g.start
        )
        if not self._fixtures and self._info is not None and self._info.next_game is not None:
            self._fixtures = [self._info.next_game]
        # A finished game in the schedule is authoritative over any live data kept from before.
        for game in self._results:
            self._live.pop(game.id, None)

        upcoming = self.next_game()
        close = upcoming is not None and upcoming.start - now <= timedelta(hours=3)
        self._succeeded("schedule", 600 if close else _INTERVALS["schedule"])
        self._prefetch_leagues([game.league_key for game in self._fixtures[:6] + self._results[:3]])

    def _prefetch_leagues(self, keys: list[str]) -> None:
        """Load the team lists of other competitions (cups, Europe) for colours and logos."""
        wanted = [key for key in dict.fromkeys(keys) if get_league(key) is not None and key not in self._teams]
        if not wanted or (self._prefetch_task is not None and not self._prefetch_task.done()):
            return

        async def load() -> None:
            changed = False
            for key in wanted:
                if await self.teams_for(key):
                    changed = True
            if changed:
                self.push_update()

        try:
            self._prefetch_task = asyncio.get_running_loop().create_task(load())
        except RuntimeError:
            self._prefetch_task = None

    async def _update_live(self, game: Game) -> None:
        league = get_league(game.league_key) or League(game.league_key or self._device_config.league, game.league_name, "")
        found: Game | None = None
        days: list[str | None] = [None]
        for zone_offset in (0, -5):  # UTC date and US Eastern date (ESPN's scoreboard days)
            day = (game.start + timedelta(hours=zone_offset)).strftime("%Y%m%d")
            if day not in days:
                days.append(day)
        for day in days:
            games, logo = await self._client.scoreboard(league, day)
            found = next((g for g in games if g.id == game.id), None)
            if league.key == self._device_config.league and day is None:
                self._scores, self._league_logo = games, logo or self._league_logo
                self._succeeded("scores", 60)
            if found is not None:
                break
        if found is None:
            info = await self._client.team(self.league, self.team_id)
            self._info = info
            if info.next_game is not None and info.next_game.id == game.id:
                found = info.next_game
        if found is None:
            raise SportsDataError(f"Game {game.id} not found on the scoreboard")

        was_final = self._live.get(game.id, game).state == "post"
        self._live[game.id] = found
        self._succeeded("live", _TICK)
        if found.state == "post" and not was_final:
            _LOG.info("[%s] Game finished: %s %s-%s %s", self.log_id, found.home.team.abbr, found.home.score,
                      found.away.score, found.away.team.abbr)
            # Let ESPN settle, then refresh the schedule, standing and table.
            soon = time.monotonic() + 90
            for task in ("schedule", "team", "table"):
                self._due[task] = min(self._due.get(task, soon), soon)

    async def _update_scores(self, league: League) -> None:
        games, logo = await self._client.scoreboard(league)
        self._scores = games
        self._learn([side.team for game in games for side in (game.home, game.away)])
        self._league_logo = logo or self._league_logo
        live = any(game.is_live for game in games)
        self._succeeded("scores", 60 if live else _INTERVALS["scores"])

    async def _update_table(self, league: League) -> None:
        self._table = await self._client.standings(league)
        self._learn([row.team for group in self._table for row in group.rows])
        self._succeeded("table", _INTERVALS["table"] if self._table else 24 * _HOUR)
