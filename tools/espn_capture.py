"""
ESPN API capture for uc-intg-sports.

Fetches the ESPN endpoints the integration will use, saves every response to
./espn_captures/ and writes a summary. Python 3.9+ standard library only.

Run:  python espn_capture.py
Then zip the espn_captures folder and send it back.
"""

import json
import os
import time
import urllib.error
import urllib.request

SITE = "https://site.api.espn.com/apis/site/v2/sports"
V2 = "https://site.api.espn.com/apis/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"
OUT = "espn_captures"

# Leagues the integration plans to offer: (sport, league slug)
LEAGUES = [
    ("soccer", "eng.1"), ("soccer", "eng.2"), ("soccer", "eng.fa"), ("soccer", "eng.league_cup"),
    ("soccer", "esp.1"), ("soccer", "ger.1"), ("soccer", "ita.1"), ("soccer", "fra.1"),
    ("soccer", "ned.1"), ("soccer", "por.1"), ("soccer", "sco.1"), ("soccer", "tur.1"),
    ("soccer", "bel.1"), ("soccer", "uefa.champions"), ("soccer", "uefa.europa"),
    ("soccer", "uefa.europa.conf"), ("soccer", "usa.1"), ("soccer", "usa.nwsl"), ("soccer", "mex.1"),
    ("soccer", "bra.1"), ("soccer", "arg.1"), ("soccer", "aus.1"), ("soccer", "jpn.1"),
    ("soccer", "ksa.1"), ("soccer", "eng.w.1"), ("soccer", "fifa.world"), ("soccer", "uefa.euro"),
    ("soccer", "conmebol.america"), ("soccer", "fifa.worldq.uefa"), ("soccer", "uefa.nations"),
    ("football", "nfl"), ("football", "college-football"),
    ("basketball", "nba"), ("basketball", "wnba"),
    ("basketball", "mens-college-basketball"), ("basketball", "womens-college-basketball"),
    ("baseball", "mlb"), ("hockey", "nhl"), ("australian-football", "afl"),
]

# Endpoints captured in full: (file name, url)
FULL = [
    ("scoreboard_eng1", f"{SITE}/soccer/eng.1/scoreboard"),
    ("scoreboard_eng1_gb", f"{SITE}/soccer/eng.1/scoreboard?lang=en&region=gb"),
    ("scoreboard_ucl", f"{SITE}/soccer/uefa.champions/scoreboard"),
    ("scoreboard_mls", f"{SITE}/soccer/usa.1/scoreboard"),
    ("scoreboard_nfl", f"{SITE}/football/nfl/scoreboard"),
    ("scoreboard_nba", f"{SITE}/basketball/nba/scoreboard"),
    ("scoreboard_mlb", f"{SITE}/baseball/mlb/scoreboard"),
    ("scoreboard_nhl", f"{SITE}/hockey/nhl/scoreboard"),
    ("scoreboard_afl", f"{SITE}/australian-football/afl/scoreboard"),
    ("scoreboard_eng1_range", f"{SITE}/soccer/eng.1/scoreboard?dates={time.strftime('%Y%m%d')}-{time.strftime('%Y%m%d', time.gmtime(time.time() + 7 * 86400))}"),
    ("teams_eng1", f"{SITE}/soccer/eng.1/teams?limit=1000"),
    ("teams_nfl", f"{SITE}/football/nfl/teams?limit=1000"),
    ("team_arsenal_eng1", f"{SITE}/soccer/eng.1/teams/359"),
    ("team_arsenal_all", f"{SITE}/soccer/all/teams/359"),
    ("schedule_arsenal_eng1", f"{SITE}/soccer/eng.1/teams/359/schedule"),
    ("schedule_arsenal_eng1_fixture", f"{SITE}/soccer/eng.1/teams/359/schedule?fixture=true"),
    ("schedule_arsenal_all", f"{SITE}/soccer/all/teams/359/schedule"),
    ("schedule_arsenal_all_fixture", f"{SITE}/soccer/all/teams/359/schedule?fixture=true"),
    ("team_chiefs", f"{SITE}/football/nfl/teams/12"),
    ("schedule_chiefs", f"{SITE}/football/nfl/teams/12/schedule"),
    ("team_celtics", f"{SITE}/basketball/nba/teams/2"),
    ("schedule_celtics", f"{SITE}/basketball/nba/teams/2/schedule"),
    ("standings_eng1", f"{V2}/soccer/eng.1/standings"),
    ("standings_nfl", f"{V2}/football/nfl/standings"),
    ("standings_nba", f"{V2}/basketball/nba/standings"),
    ("standings_mlb", f"{V2}/baseball/mlb/standings"),
    ("soccer_league_catalog", f"{CORE}/soccer/leagues?limit=500"),
]

LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/359.png"


def fetch(url: str) -> tuple[int, bytes, float]:
    start = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), time.time() - start
    except urllib.error.HTTPError as err:
        return err.code, err.read() or b"", time.time() - start
    except Exception as err:  # noqa: BLE001
        return 0, str(err).encode(), time.time() - start


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    summary = []

    for name, url in FULL:
        status, body, took = fetch(url)
        with open(os.path.join(OUT, f"{name}.json"), "wb") as file:
            file.write(body)
        summary.append(f"{status}  {took:5.2f}s  {len(body):>9}B  {name}  {url}")
        print(summary[-1])
        time.sleep(0.3)

    for sport, league in LEAGUES:
        url = f"{SITE}/{sport}/{league}/teams?limit=1000"
        status, body, took = fetch(url)
        teams = 0
        try:
            teams = len(json.loads(body)["sports"][0]["leagues"][0]["teams"])
        except Exception:  # noqa: BLE001
            pass
        summary.append(f"{status}  {took:5.2f}s  teams={teams:<4}  league {sport}/{league}")
        print(summary[-1])
        time.sleep(0.3)

    status, body, took = fetch(LOGO)
    summary.append(f"{status}  {took:5.2f}s  {len(body):>9}B  logo  {LOGO}")
    print(summary[-1])

    summary.append(f"local time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as file:
        file.write("\n".join(summary) + "\n")
    print(f"\nDone. Zip the '{OUT}' folder and send it back.")


if __name__ == "__main__":
    main()
