"""
Display preferences: time and date format, matchup order and time zone.

ESPN's own status text is fixed to US Eastern time ("10/4 - 1:00 PM EDT"), so
every time shown to the user is formatted here from the UTC start time.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

from uc_intg_sports.model import Game, Side

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

_LOG = logging.getLogger(__name__)

TIME_12H = "12h"
TIME_24H = "24h"
DATE_US = "us"  # Sat, Oct 10
DATE_INTL = "intl"  # Sat 10 Oct
HOME_FIRST = "home_away"  # Arsenal v Leeds
AWAY_FIRST = "away_home"  # Leeds @ Arsenal
AUTO_TZ = "auto"

REGION_US = "us"
REGION_INTL = "intl"
REGIONS = {
    REGION_US: (TIME_12H, DATE_US, AWAY_FIRST),
    REGION_INTL: (TIME_24H, DATE_INTL, HOME_FIRST),
}

# Common time zones offered in setup and in the Time Zone select.
TIME_ZONES = (
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
    "America/Anchorage", "Pacific/Honolulu", "America/Toronto", "America/Vancouver", "America/Halifax",
    "America/Mexico_City", "America/Bogota", "America/Lima", "America/Santiago", "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires", "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Madrid",
    "Europe/Paris", "Europe/Amsterdam", "Europe/Brussels", "Europe/Berlin", "Europe/Zurich", "Europe/Rome",
    "Europe/Stockholm", "Europe/Oslo", "Europe/Copenhagen", "Europe/Warsaw", "Europe/Prague", "Europe/Vienna",
    "Europe/Athens", "Europe/Helsinki", "Europe/Istanbul", "Asia/Jerusalem", "Africa/Cairo",
    "Africa/Johannesburg", "Africa/Lagos", "Asia/Riyadh", "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok",
    "Asia/Singapore", "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Australia/Perth",
    "Australia/Adelaide", "Australia/Brisbane", "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland",
    "UTC",
)


@dataclass(frozen=True)
class Prefs:
    time_format: str = TIME_24H
    date_format: str = DATE_INTL
    matchup: str = HOME_FIRST
    time_zone: str = AUTO_TZ


def get_tz(name: str) -> tzinfo:
    """Return the configured zone, or the Remote's local zone."""
    if name and name != AUTO_TZ and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as err:
            _LOG.warning("Unknown time zone %s, using local time: %s", name, err)
    return datetime.now().astimezone().tzinfo or timezone.utc


def local(when: datetime, prefs: Prefs) -> datetime:
    return when.astimezone(get_tz(prefs.time_zone))


def now(prefs: Prefs) -> datetime:
    return datetime.now(timezone.utc).astimezone(get_tz(prefs.time_zone))


def fmt_time(when: datetime, prefs: Prefs) -> str:
    when = local(when, prefs)
    if prefs.time_format == TIME_12H:
        return when.strftime("%I:%M %p").lstrip("0")
    return when.strftime("%H:%M")


def fmt_day(when: datetime, prefs: Prefs, relative: bool = True) -> str:
    """"Today", "Tomorrow", "Sat, Oct 10" or "Sat 10 Oct"."""
    when = local(when, prefs)
    if relative:
        days = (when.date() - now(prefs).date()).days
        if days == 0:
            return "Today"
        if days == 1:
            return "Tomorrow"
        if days == -1:
            return "Yesterday"
    if prefs.date_format == DATE_US:
        return f"{when:%a}, {when:%b} {when.day}"
    return f"{when:%a} {when.day} {when:%b}"


def fmt_kickoff(game: Game, prefs: Prefs, relative: bool = True) -> str:
    """Day and start time, e.g. "Sat 10 Oct, 12:30" or "Today, 7:30 PM"."""
    day = fmt_day(game.start, prefs, relative)
    if not game.time_valid:
        return f"{day}, time TBD"
    return f"{day}, {fmt_time(game.start, prefs)}"


def countdown(start: datetime, current: datetime | None = None) -> str:
    """"in 6 days", "in 5h 20m", "in 12 min", "starting soon"."""
    current = current or datetime.now(timezone.utc)
    seconds = (start - current).total_seconds()
    if seconds <= 60:
        return "starting soon"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"in {minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"in {hours}h {minutes // 5 * 5:02d}m"
    days = round(seconds / 86400)
    return "in 1 day" if days == 1 else f"in {days} days"


def ordered(game: Game, prefs: Prefs) -> tuple[Side, Side, str]:
    """Return (first, second, joiner) in the preferred matchup order."""
    if prefs.matchup == AWAY_FIRST:
        return game.away, game.home, "@"
    return game.home, game.away, "v"


def matchup(game: Game, prefs: Prefs, short: bool = False) -> str:
    first, second, joiner = ordered(game, prefs)
    name = (lambda side: side.team.short) if short else (lambda side: side.team.name)
    return f"{name(first)} {joiner} {name(second)}"


def score_line(game: Game, prefs: Prefs) -> str:
    """"ARS 2-1 CHE" in the preferred order, with penalties when used."""
    first, second, _ = ordered(game, prefs)
    line = f"{first.team.abbr} {first.score or 0}-{second.score or 0} {second.team.abbr}"
    if first.shootout or second.shootout:
        line += f" ({first.shootout or 0}-{second.shootout or 0} pens)"
    return line


def status_label(game: Game, soccer: bool) -> str:
    """Short live or final label: "67'", "HT", "FT", "Q4 0:48", "Final/OT", "Postponed"."""
    status = game.status
    if game.is_off:
        for word, label in (("POSTPONED", "Postponed"), ("CANCEL", "Cancelled"), ("ABANDONED", "Abandoned"),
                            ("SUSPENDED", "Suspended")):
            if word in status:
                return label
    if game.state == "post":
        if soccer:
            if "PEN" in status or game.home.shootout or game.away.shootout:
                return "FT (pens)"
            if "AET" in status or "EXTRA" in status:
                return "AET"
            return "FT"
        return game.detail or "Final"
    if game.state == "in":
        if soccer:
            if "HALFTIME" in status:
                return "HT"
            if "END_OF_REGULATION" in status or "END_EXTRA" in status:
                return "Break"
            if "SHOOTOUT" in status:
                return "Penalties"
            return game.clock or game.detail or "Live"
        return game.detail or game.clock or "Live"
    return ""
