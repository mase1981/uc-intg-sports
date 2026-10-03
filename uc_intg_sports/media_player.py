"""
Sports media players.

Two artwork tiles per followed team, so even several teams stay well inside
the Remote's image cache (12 media players with artwork):

  Team tile    next game, live score or the result. Next / Previous step
               through recent results and upcoming games.
  League card  the league scoreboard or the league table. Next / Previous
               page through it; the input source switches Scores / Table.

Both report the ON state, not PLAYING: a PLAYING media player is treated by
the Remote as a running activity (power menu, page header).

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from ucapi import StatusCodes, media_player
from ucapi_framework import MediaPlayerEntity

from uc_intg_sports import art
from uc_intg_sports.config import VIEW_SCORES, VIEW_TABLE, SportsConfig
from uc_intg_sports.device import SportsDevice
from uc_intg_sports.model import Game, Side, TableGroup
from uc_intg_sports.prefs import (
    countdown,
    fmt_day,
    fmt_kickoff,
    fmt_time,
    local,
    matchup,
    now,
    ordered,
    score_line,
    status_label,
)

_LOG = logging.getLogger(__name__)

_TILE_FEATURES = [
    media_player.Features.ON_OFF,
    media_player.Features.NEXT,
    media_player.Features.PREVIOUS,
]
_CARD_FEATURES = _TILE_FEATURES + [media_player.Features.SELECT_SOURCE]
_SOURCES = {VIEW_SCORES: "Scores", VIEW_TABLE: "Table"}
_BROWSE_RESET = 600  # seconds before Next / Previous browsing returns to the default view


def _empty_attributes() -> dict[str, Any]:
    return {
        media_player.Attributes.STATE: media_player.States.UNKNOWN,
        media_player.Attributes.MEDIA_TITLE: "",
        media_player.Attributes.MEDIA_ARTIST: "",
        media_player.Attributes.MEDIA_ALBUM: "",
        media_player.Attributes.MEDIA_IMAGE_URL: "",
    }


def _short_standing(standing: str) -> str:
    """"2nd in English Premier League" -> "2nd"."""
    return standing.split(" in ", 1)[0] if " in " in standing else standing


class _ArtworkMixin:
    """Render once per distinct spec; reuse the data URL otherwise."""

    _spec_key: Any = None
    _image_url: str = ""

    async def _artwork(self, spec: Any, renderer: Callable[[Any, dict], bytes], logos: dict) -> str:
        key = (spec, tuple(sorted(logos)))
        if key == self._spec_key and self._image_url:
            return self._image_url
        try:
            data = await asyncio.to_thread(renderer, spec, logos)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.warning("Artwork render failed: %s", err)
            return self._image_url
        self._image_url = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
        self._spec_key = key
        return self._image_url


class SportsTeamPlayer(_ArtworkMixin, MediaPlayerEntity):
    """The followed team's match tile."""

    def __init__(self, device_config: SportsConfig, device: SportsDevice) -> None:
        self._device = device
        self._offset = 0
        self._browsed_at = 0.0
        self._browse_anchor = ""  # id of the default game when browsing started
        super().__init__(
            f"media_player.{device_config.identifier}",
            device_config.name,
            _TILE_FEATURES,
            _empty_attributes(),
            device_class=media_player.DeviceClasses.RECEIVER,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    # -- data -----------------------------------------------------------
    def _selected(self) -> Game | None:
        games = self._device.timeline()
        if not games:
            return None
        focus = self._device.focus(games)
        # Return to the default game after a while, or as soon as it changes (e.g. kick-off).
        if self._offset and (time.monotonic() - self._browsed_at > _BROWSE_RESET
                             or games[focus].id != self._browse_anchor):
            self._offset = 0
        index = max(0, min(len(games) - 1, focus + self._offset))
        return games[index]

    async def _side_view(self, side: Side, game: Game, logos: dict) -> art.SideView:
        url, image = await self._device.team_logo(side.team)
        if image is not None:
            logos[url] = image
        soccer = self._device.league.is_soccer or game.league_key.startswith("soccer/")
        detail = ""
        if game.state == "pre":
            if soccer:
                info = self._device.info
                if side.team.id == self._device.team_id and info is not None:
                    detail = _short_standing(info.standing)
            else:
                detail = side.record
        plays = []
        reds = 0
        for play in game.plays:
            if play.team_id != side.team.id:
                continue
            if play.kind == "red_card":
                reds += 1
                continue
            suffix = " (P)" if play.kind == "penalty" else " (OG)" if play.kind == "own_goal" else ""
            plays.append(f"{play.minute} {play.text}{suffix}".strip())
        return art.SideView(
            name=side.team.short or side.team.name,
            abbr=side.team.abbr,
            color=side.team.color,
            logo=url,
            score=side.score,
            shootout=side.shootout,
            winner=side.winner,
            detail=detail,
            plays=tuple(plays) if game.state != "pre" else (),
            red_cards=reds if game.state != "pre" else 0,
            possession=game.is_live and bool(game.possession) and game.possession == side.team.id,
        )

    async def _match_spec(self, game: Game, logos: dict) -> art.MatchCard:
        prefs = self._device.prefs
        soccer = game.league_key.startswith("soccer/") or self._device.league.is_soccer
        first, second, joiner = ordered(game, prefs)
        first_view = await self._side_view(first, game, logos)
        second_view = await self._side_view(second, game, logos)
        league = game.league_name or self._device.league.name
        venue_tv = "  •  ".join(part for part in (game.venue, ", ".join(game.broadcasts[:2])) if part)

        if game.is_off:
            kind = "off"
        elif game.is_live:
            kind = "live"
        elif game.state == "post":
            kind = "final"
        else:
            kind = "pre"

        if kind == "pre":
            current = datetime.now(timezone.utc)
            return art.MatchCard(
                kind="pre",
                league=league,
                first=first_view,
                second=second_view,
                joiner=joiner,
                big_time=fmt_time(game.start, prefs) if game.time_valid else "TBD",
                day=fmt_day(game.start, prefs),
                # Changes at most every 5 minutes (see countdown), so the card is rarely redrawn.
                countdown=countdown(game.start, current) if game.time_valid else "",
                footer=venue_tv,
                stale=self._device.stale("schedule"),
                text_size=self._device.text_size,
            )
        if kind == "off":
            return art.MatchCard(
                kind="off", league=league, first=first_view, second=second_view, joiner=joiner,
                status=status_label(game, soccer), day=fmt_day(game.start, prefs, relative=False), footer=game.venue,
                text_size=self._device.text_size,
            )
        return art.MatchCard(
            kind=kind,
            league=league,
            first=first_view,
            second=second_view,
            joiner=joiner,
            status=status_label(game, soccer),
            footer=venue_tv if kind == "live" else fmt_day(game.start, prefs, relative=False),
            situation=game.situation if game.possession or game.outs is None else "",
            outs=game.outs if game.is_live else None,
            bases=game.bases if game.is_live and game.outs is not None else None,
            count=game.count if game.is_live else "",
            stale=kind == "live" and self._device.stale("live"),
            text_size=self._device.text_size,
        )

    def _texts(self, game: Game) -> tuple[str, str, str]:
        prefs = self._device.prefs
        soccer = game.league_key.startswith("soccer/") or self._device.league.is_soccer
        title = matchup(game, prefs)
        league = game.league_name or self._device.league.name
        if game.is_off:
            artist = f"{status_label(game, soccer)} • was {fmt_kickoff(game, prefs)}"
        elif game.is_live:
            artist = f"LIVE {status_label(game, soccer)} • {score_line(game, prefs)}"
        elif game.state == "post":
            artist = f"{status_label(game, soccer)} • {score_line(game, prefs)}"
        else:
            when = fmt_kickoff(game, prefs)
            artist = f"{when} • {countdown(game.start)}" if game.time_valid else when
        album = "  •  ".join(part for part in (league, game.venue) if part)
        return title, artist, album

    # -- entity ---------------------------------------------------------
    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({media_player.Attributes.STATE: media_player.States.UNAVAILABLE})
            return
        attributes: dict[str, Any] = {media_player.Attributes.STATE: media_player.States.ON}
        game = self._selected()
        team = self._device.team
        logos: dict = {}
        if game is not None:
            title, artist, album = self._texts(game)
            spec = await self._match_spec(game, logos)
            renderer = art.render_match
        else:
            url, image = await self._device.team_logo(team) if team.logo or team.logo_dark else ("", None)
            if image is not None:
                logos[url] = image
            if self._device.has_data:
                message = "No games scheduled"
                lines = (self._device.info.standing,) if self._device.info and self._device.info.standing else ()
            elif self._device.stale():
                message, lines = "Scores temporarily unavailable", ("Retrying automatically",)
            else:
                message, lines = "Loading…", ()
            title, artist, album = team.name, message, self._device.league.name
            spec = art.MessageCard(team.name, message, color=team.color, logo=url, lines=lines,
                                   text_size=self._device.text_size)
            renderer = art.render_message
        attributes[media_player.Attributes.MEDIA_TITLE] = title
        attributes[media_player.Attributes.MEDIA_ARTIST] = artist
        attributes[media_player.Attributes.MEDIA_ALBUM] = album
        attributes[media_player.Attributes.MEDIA_IMAGE_URL] = await self._artwork(spec, renderer, logos)
        self.update(attributes)

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        if cmd_id in (media_player.Commands.NEXT, media_player.Commands.PREVIOUS):
            games = self._device.timeline()
            if games:
                focus = self._device.focus(games)
                if not self._offset:
                    self._browse_anchor = games[focus].id
                step = 1 if cmd_id == media_player.Commands.NEXT else -1
                self._offset = max(-focus, min(len(games) - 1 - focus, self._offset + step))
                self._browsed_at = time.monotonic()
            await self.sync_state()
            return StatusCodes.OK
        if cmd_id == media_player.Commands.ON:
            self._offset = 0
            await self._device.refresh()
            return StatusCodes.OK
        if cmd_id in (media_player.Commands.OFF, media_player.Commands.PLAY_PAUSE):
            self._offset = 0
            await self.sync_state()
            return StatusCodes.OK
        return StatusCodes.NOT_IMPLEMENTED


class SportsLeagueCard(_ArtworkMixin, MediaPlayerEntity):
    """League scoreboard or table for the followed team's league."""

    def __init__(self, device_config: SportsConfig, device: SportsDevice) -> None:
        self._device = device
        self._page = 0
        self._paged_at = 0.0
        attributes = _empty_attributes()
        attributes[media_player.Attributes.SOURCE_LIST] = list(_SOURCES.values())
        attributes[media_player.Attributes.SOURCE] = _SOURCES[device.card_view]
        super().__init__(
            f"media_player.{device_config.identifier}.league",
            f"{device_config.name} League",
            _CARD_FEATURES,
            attributes,
            device_class=media_player.DeviceClasses.RECEIVER,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    # -- scoreboard -------------------------------------------------------
    def _score_pages(self) -> tuple[list[list[Game]], int]:
        games = sorted(self._device.scores, key=lambda game: (game.start, game.home.team.name))
        size = art.score_rows(self._device.text_size)
        pages = [games[i:i + size] for i in range(0, len(games), size)] or [[]]
        default = 0
        for index, page in enumerate(pages):
            if any(game.side_of(self._device.team_id) for game in page):
                default = index
                break
        for index, page in enumerate(pages):
            if any(game.is_live for game in page):
                default = index
                break
        return pages, default

    def _score_status(self, game: Game, soccer: bool, same_day: bool) -> str:
        prefs = self._device.prefs
        if game.is_live or game.state == "post":
            return status_label(game, soccer)
        if not game.time_valid:
            return "TBD"
        if same_day or local(game.start, prefs).date() == now(prefs).date():
            return fmt_time(game.start, prefs)
        return f"{local(game.start, prefs):%a} {fmt_time(game.start, prefs)}"

    async def _scores_spec(self, logos: dict) -> tuple[art.ScoresCard, str]:
        prefs = self._device.prefs
        soccer = self._device.league.is_soccer
        pages, default = self._score_pages()
        page = self._page_index(len(pages), default)
        days = sorted({local(game.start, prefs).date() for game in pages[page]})
        rows = []
        for game in pages[page]:
            first, second, _ = ordered(game, prefs)
            urls = []
            for team in (first.team, second.team):
                url, image = await self._device.team_logo(team)
                if image is not None:
                    logos[url] = image
                urls.append(url)
            rows.append(
                art.ScoreRow(
                    first=first.team.abbr, first_logo=urls[0], first_score=first.score,
                    second=second.team.abbr, second_logo=urls[1], second_score=second.score,
                    status=self._score_status(game, soccer, len(days) == 1),
                    live=game.is_live, final=game.state == "post" and not game.is_off,
                    highlight=game.side_of(self._device.team_id) is not None,
                )
            )
        if len(days) == 1 and pages[page]:
            subtitle = fmt_day(pages[page][0].start, prefs)
        elif days:
            subtitle = f"{fmt_day(pages[page][0].start, prefs, False)} - {fmt_day(pages[page][-1].start, prefs, False)}"
        else:
            subtitle = "Scores"
        logo = await self._league_logo(logos)
        live = sum(1 for game in self._device.scores if game.is_live)
        summary = f"{live} live" if live else f"{len(self._device.scores)} games"
        spec = art.ScoresCard(
            title=self._device.league.name, subtitle=subtitle, rows=tuple(rows),
            page=f"{page + 1}/{len(pages)}" if len(pages) > 1 else "", league_logo=logo,
            stale=self._device.stale("scores"), text_size=self._device.text_size,
        )
        return spec, summary

    # -- table ------------------------------------------------------------
    def _table_pages(self) -> tuple[list[tuple[TableGroup, int]], int]:
        """Pages of (group, first row index); default page holds the followed team."""
        pages: list[tuple[TableGroup, int]] = []
        default = 0
        size = art.table_rows(self._device.text_size)
        for group in self._device.table:
            for start in range(0, max(1, len(group.rows)), size):
                if any(row.team.id == self._device.team_id for row in group.rows[start:start + size]):
                    default = len(pages)
                pages.append((group, start))
        return pages, default

    def _columns(self) -> tuple[tuple[str, ...], tuple[int, ...], Callable[[Any], tuple[str, ...]]]:
        """Column titles, how long each is kept when space is short, and the values."""
        sport = self._device.league.sport
        if sport == "soccer":
            return ("P", "GD", "Pts"), (1, 2, 3), lambda row: (row.played, row.diff, row.points)
        if sport == "hockey":
            return ("GP", "W", "L", "Pts"), (1, 2, 2, 3), lambda row: (row.played, row.wins, row.losses, row.points)
        if sport == "australian-football":
            return ("P", "W", "L", "Pts"), (1, 2, 2, 3), lambda row: (row.played, row.wins, row.losses, row.points)
        if sport == "football":
            return ("W", "L", "PCT"), (3, 3, 1), lambda row: (row.wins, row.losses, row.pct)
        return ("W", "L", "PCT", "GB"), (3, 3, 1, 2), lambda row: (row.wins, row.losses, row.pct, row.behind)

    async def _table_spec(self, logos: dict) -> tuple[art.TableCard, str]:
        pages, default = self._table_pages()
        columns, keep, values = self._columns()
        summary = "Table"
        lines = []
        subtitle = "Table"
        page_text = ""
        if pages:
            page = self._page_index(len(pages), default)
            group, start = pages[page]
            subtitle = group.name
            page_text = f"{page + 1}/{len(pages)}" if len(pages) > 1 else ""
            for row in group.rows[start:start + art.table_rows(self._device.text_size)]:
                url, image = await self._device.team_logo(row.team)
                if image is not None:
                    logos[url] = image
                followed = row.team.id == self._device.team_id
                lines.append(
                    art.TableLine(
                        rank=str(row.rank), name=row.team.short or row.team.name, logo=url,
                        values=tuple(value or "-" for value in values(row)), highlight=followed,
                        note_color=row.note_color,
                    )
                )
            for group_rows in self._device.table:
                for row in group_rows.rows:
                    if row.team.id == self._device.team_id:
                        summary = f"{row.team.short}: #{row.rank}" + (f", {row.points} pts" if row.points else "")
        logo = await self._league_logo(logos)
        spec = art.TableCard(
            title=self._device.league.name, subtitle=subtitle, columns=columns, lines=tuple(lines), keep=keep,
            page=page_text, league_logo=logo, stale=self._device.stale("table"), text_size=self._device.text_size,
        )
        return spec, summary

    # -- shared -----------------------------------------------------------
    async def _league_logo(self, logos: dict) -> str:
        url = self._device.league_logo
        if url:
            logos.update(await self._device.logos([url]))
        return url if url in logos else ""

    def _page_index(self, count: int, default: int) -> int:
        if self._paged_at and time.monotonic() - self._paged_at > _BROWSE_RESET:
            self._page, self._paged_at = 0, 0.0
        if not self._paged_at:
            return max(0, min(count - 1, default))
        return self._page % max(1, count)

    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({media_player.Attributes.STATE: media_player.States.UNAVAILABLE})
            return
        view = self._device.card_view
        logos: dict = {}
        if view == VIEW_TABLE:
            spec, summary = await self._table_spec(logos)
            renderer = art.render_table
        else:
            spec, summary = await self._scores_spec(logos)
            renderer = art.render_scores
        self.update(
            {
                media_player.Attributes.STATE: media_player.States.ON,
                media_player.Attributes.MEDIA_TITLE: f"{self._device.league.name} • {_SOURCES[view]}",
                media_player.Attributes.MEDIA_ARTIST: summary,
                media_player.Attributes.MEDIA_ALBUM: spec.subtitle,
                media_player.Attributes.SOURCE: _SOURCES[view],
                media_player.Attributes.SOURCE_LIST: list(_SOURCES.values()),
                media_player.Attributes.MEDIA_IMAGE_URL: await self._artwork(spec, renderer, logos),
            }
        )

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        if cmd_id in (media_player.Commands.NEXT, media_player.Commands.PREVIOUS):
            if self._device.card_view == VIEW_TABLE:
                pages, default = self._table_pages()
            else:
                pages, default = self._score_pages()
            current = self._page_index(len(pages), default)
            step = 1 if cmd_id == media_player.Commands.NEXT else -1
            self._page = (current + step) % max(1, len(pages))
            self._paged_at = time.monotonic()
            await self.sync_state()
            return StatusCodes.OK
        if cmd_id == media_player.Commands.SELECT_SOURCE:
            source = (params or {}).get("source", "")
            view = next((key for key, label in _SOURCES.items() if label == source), None)
            if view is None:
                return StatusCodes.BAD_REQUEST
            self._page, self._paged_at = 0, 0.0
            self._device.set_card_view(view)
            await self.sync_state()
            return StatusCodes.OK
        if cmd_id == media_player.Commands.ON:
            self._page, self._paged_at = 0, 0.0
            await self._device.refresh()
            return StatusCodes.OK
        if cmd_id in (media_player.Commands.OFF, media_player.Commands.PLAY_PAUSE):
            return StatusCodes.OK
        return StatusCodes.NOT_IMPLEMENTED


def create_media_players(device_config: SportsConfig, device: SportsDevice) -> list[MediaPlayerEntity]:
    return [SportsTeamPlayer(device_config, device), SportsLeagueCard(device_config, device)]

