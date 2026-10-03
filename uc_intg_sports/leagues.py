"""
League catalog.

Every league listed here was checked against the ESPN teams endpoint. The key
is "<sport>/<league slug>" as used in the ESPN API paths.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

from dataclasses import dataclass

SOCCER = "soccer"


@dataclass(frozen=True)
class League:
    """One competition the integration can follow."""

    key: str  # "soccer/eng.1"
    name: str  # display name
    group: str  # heading used to order the list

    @property
    def sport(self) -> str:
        return self.key.split("/", 1)[0]

    @property
    def slug(self) -> str:
        return self.key.split("/", 1)[1]

    @property
    def is_soccer(self) -> bool:
        return self.sport == SOCCER

    @property
    def label(self) -> str:
        return f"{self.group} - {self.name}"


_LEAGUES = (
    # Soccer - Europe
    League("soccer/eng.1", "Premier League", "England"),
    League("soccer/eng.2", "Championship", "England"),
    League("soccer/eng.fa", "FA Cup", "England"),
    League("soccer/eng.league_cup", "EFL Cup", "England"),
    League("soccer/eng.w.1", "Women's Super League", "England"),
    League("soccer/sco.1", "Scottish Premiership", "Scotland"),
    League("soccer/esp.1", "LaLiga", "Spain"),
    League("soccer/ger.1", "Bundesliga", "Germany"),
    League("soccer/ita.1", "Serie A", "Italy"),
    League("soccer/fra.1", "Ligue 1", "France"),
    League("soccer/ned.1", "Eredivisie", "Netherlands"),
    League("soccer/por.1", "Primeira Liga", "Portugal"),
    League("soccer/bel.1", "Pro League", "Belgium"),
    League("soccer/tur.1", "Super Lig", "Turkey"),
    League("soccer/uefa.champions", "Champions League", "UEFA"),
    League("soccer/uefa.europa", "Europa League", "UEFA"),
    League("soccer/uefa.europa.conf", "Conference League", "UEFA"),
    League("soccer/uefa.nations", "Nations League", "UEFA"),
    League("soccer/uefa.euro", "European Championship", "UEFA"),
    # Soccer - Americas, Asia, Oceania, international
    League("soccer/usa.1", "MLS", "USA"),
    League("soccer/usa.nwsl", "NWSL", "USA"),
    League("soccer/mex.1", "Liga MX", "Mexico"),
    League("soccer/bra.1", "Brasileirao", "Brazil"),
    League("soccer/arg.1", "Liga Profesional", "Argentina"),
    League("soccer/conmebol.america", "Copa America", "CONMEBOL"),
    League("soccer/ksa.1", "Saudi Pro League", "Saudi Arabia"),
    League("soccer/jpn.1", "J1 League", "Japan"),
    League("soccer/aus.1", "A-League Men", "Australia"),
    League("soccer/fifa.world", "World Cup", "FIFA"),
    League("soccer/fifa.worldq.uefa", "World Cup Qualifying - UEFA", "FIFA"),
    # North American and other team sports
    League("football/nfl", "NFL", "American Football"),
    League("football/college-football", "College Football", "American Football"),
    League("basketball/nba", "NBA", "Basketball"),
    League("basketball/wnba", "WNBA", "Basketball"),
    League("basketball/mens-college-basketball", "Men's College Basketball", "Basketball"),
    League("basketball/womens-college-basketball", "Women's College Basketball", "Basketball"),
    League("baseball/mlb", "MLB", "Baseball"),
    League("hockey/nhl", "NHL", "Ice Hockey"),
    League("australian-football/afl", "AFL", "Australian Football"),
)

LEAGUES: dict[str, League] = {league.key: league for league in _LEAGUES}


def get_league(key: str) -> League | None:
    return LEAGUES.get(key)


def league_by_label(label: str) -> League | None:
    return next((league for league in _LEAGUES if league.label == label), None)


def league_labels() -> list[str]:
    return [league.label for league in _LEAGUES]
