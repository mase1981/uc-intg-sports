# Sports Integration for Unfolded Circle Remote 2/3

Follow your teams on your Unfolded Circle Remote: live scores, upcoming games and league tables as custom artwork, with sensors and select entities for every setting. Soccer from around the world, NFL, NBA, MLB, NHL, AFL, college sports and more.

[![GitHub Release](https://img.shields.io/github/v/release/mase1981/uc-intg-sports?style=flat-square)](https://github.com/mase1981/uc-intg-sports/releases)
![License](https://img.shields.io/badge/license-MPL--2.0-blue?style=flat-square)
[![GitHub issues](https://img.shields.io/github/issues/mase1981/uc-intg-sports?style=flat-square)](https://github.com/mase1981/uc-intg-sports/issues)
[![Community Forum](https://img.shields.io/badge/community-forum-blue?style=flat-square)](https://unfolded.community/)
[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/mase1981/uc-intg-sports/total?style=flat-square)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=flat-square)](https://buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-donate-blue.svg?style=flat-square)](https://paypal.me/mmiyara)
[![Github Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-30363D?&logo=GitHub-Sponsors&logoColor=EA4AAA&style=flat-square)](https://github.com/sponsors/mase1981)

---
## ❤️ Support Development ❤️

If you find this integration useful, consider supporting development:

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/mase1981)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/mmiyara)

Your support helps maintain this integration. Thank you! ❤️
---

## Features

### Team Tile (media player with custom artwork)
- **Before the game** - Both teams in their colours with logos, kick-off time in your time zone, a countdown, venue and TV channel
- **During the game** - Live score and clock, goal scorers and red cards (soccer), possession and down & distance (American football), count, outs and bases (baseball)
- **After the game** - Final score with the winner highlighted and the scorers, then it moves on to the next game
- **Next / Previous** - Step through recent results and upcoming games; it returns to the current game on its own
- **Every competition** - Soccer clubs show league, cup and European games together

### League Card (media player with custom artwork)
- **Scores** - The league's current scoreboard, your team's game highlighted
- **Table** - The league table or conference standings around your team, with qualification colours
- **Switch** - Use the input source (Scores / Table) or the League Card select; Next / Previous pages through it

### Select Entities
| Select | Options |
|--------|---------|
| League | Choose a league; the Team select then lists its teams |
| Team | Follow another team without running setup again |
| Region | United States (12-hour, Oct 10, Away @ Home) or International (24-hour, 10 Oct, Home v Away) |
| Time Format | 12-hour (7:30 PM) or 24-hour (19:30) |
| Date Format | Sat, Oct 10 or Sat 10 Oct |
| Matchup Order | Home v Away or Away @ Home |
| Time Zone | The Remote's own time zone or a fixed one |
| League Card | Scores or Table |
| Text Size | Normal, Large or Extra Large artwork text |

### Text Size
- **Normal** - Most detail: venue and TV, records, up to three scorers per team, 6 games or 10 table rows per page
- **Large** and **Extra Large** - Bigger text for reading from the couch; the cards re-flow and show fewer rows per page, and the least important lines are left out first
- Choose it during setup or change it any time with the Text Size select

### Sensors
- **Score**, **Game Status**, **Next Game**, **Next Kickoff**, **Last Result**, **Standing**, **Record**
- Use them on Remote pages or in activities

### Button
- **Refresh** - Fetch everything now

## Leagues

| Sport | Leagues |
|-------|---------|
| Soccer - Europe | Premier League, Championship, FA Cup, EFL Cup, Women's Super League, Scottish Premiership, LaLiga, Bundesliga, Serie A, Ligue 1, Eredivisie, Primeira Liga, Belgian Pro League, Super Lig, Champions League, Europa League, Conference League, Nations League, European Championship |
| Soccer - World | MLS, NWSL, Liga MX, Brasileirao, Argentine Liga Profesional, Copa America, Saudi Pro League, J1 League, A-League Men, World Cup, World Cup Qualifying (UEFA) |
| American Football | NFL, College Football |
| Basketball | NBA, WNBA, Men's and Women's College Basketball |
| Baseball | MLB |
| Ice Hockey | NHL |
| Australian Football | AFL |

## Reliability

- **No account or API key** - Nothing to sign up for
- **Light on the network** - Team and table every few hours, the schedule hourly, live scores every 30 seconds only while your team is playing
- **Keeps working through outages** - If the data cannot be refreshed, the last scores stay on screen with a small "updating…" badge and the integration retries with growing delays
- **Times are always yours** - Kick-off times are converted to your time zone and format; nothing is shown in US Eastern time
- **Logos cached** - Downloaded once and kept on the Remote

> **Data source:** Scores come from ESPN's public data feed, the same feed used by other home-automation projects for years. It is not an official API and this integration is not affiliated with or endorsed by ESPN. If ESPN changes the feed, an update of this integration may be needed.

## Installation

### Option 1: Remote Web Interface (Recommended)
1. Navigate to the [**Releases**](https://github.com/mase1981/uc-intg-sports/releases) page
2. Download the latest `uc-intg-sports-<version>-aarch64.tar.gz` file
3. Open your remote's web interface (`http://your-remote-ip`)
4. Go to **Settings** → **Integrations** → **Add Integration**
5. Click **Upload** and select the downloaded `.tar.gz` file

### Option 2: Docker (Advanced Users)

**Image**: `ghcr.io/mase1981/uc-intg-sports:latest`

**Docker Compose:**
```yaml
services:
  uc-intg-sports:
    image: ghcr.io/mase1981/uc-intg-sports:latest
    container_name: uc-intg-sports
    network_mode: host
    volumes:
      - </local/path>:/config
    environment:
      - UC_CONFIG_HOME=/config
      - UC_INTEGRATION_HTTP_PORT=9090
      - UC_INTEGRATION_INTERFACE=0.0.0.0
      - PYTHONPATH=/app
    restart: unless-stopped
```

**Docker Run:**
```bash
docker run -d --name uc-intg-sports --restart unless-stopped --network host -v sports-config:/config -e UC_CONFIG_HOME=/config -e UC_INTEGRATION_INTERFACE=0.0.0.0 -e UC_INTEGRATION_HTTP_PORT=9090 -e PYTHONPATH=/app ghcr.io/mase1981/uc-intg-sports:latest
```

When running in Docker, set the **Time Zone** select (or the setup option) if the container does not use your local time zone.

## Setup

1. Go to **Settings** → **Integrations**, find **Sports** and click **Configure**
2. **Step 1** - Choose your display style (United States or International), the league, the time zone and the artwork text size
3. **Step 2** - Choose your team and, optionally, a display name
4. Add the tiles, selects and sensors you want to your pages

Run setup again to follow more teams. Each team gets its own two tiles.

> **Tip:** The Remote keeps artwork for up to 12 media players at a time. Each followed team uses two, so up to five teams together with other integrations' artwork work well.

## Credits

- **Developer**: Meir Miyara
- **Data**: ESPN public data feed (not affiliated)
- **Unfolded Circle**: Remote 2/3 integration framework (ucapi, ucapi-framework)
- **Fonts**: DejaVu Sans

## License

This project is licensed under the Mozilla Public License 2.0 (MPL-2.0) - see LICENSE file for details.

## Support & Community

- **GitHub Issues**: [Report bugs and request features](https://github.com/mase1981/uc-intg-sports/issues)
- **UC Community Forum**: [General discussion and support](https://unfolded.community/)
- **Developer**: [Meir Miyara](https://www.linkedin.com/in/meirmiyara)

---

**Made with ❤️ for the Unfolded Circle Community**

**Thank You**: Meir Miyara
