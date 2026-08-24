"""Scraper for ligainsider.de: injuries/suspensions and predicted lineups.

The site is server-rendered; robots.txt allows crawling. We still keep it
polite: one session, browser UA, a fixed delay between requests.
"""

import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.ligainsider.de"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 1.0

PLAYER_HREF = re.compile(r"^/[a-z0-9-]+_\d+/$")
TEAM_HREF = re.compile(r"^/[a-z0-9-]+/\d+/$")


class LigainsiderScraper:
    def __init__(self):
        self._session = requests.Session()
        self._session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=3,
                    backoff_factor=2,
                    status_forcelist=(429, 500, 502, 503, 504),
                    raise_on_status=False,
                )
            ),
        )
        self._session.headers["User-Agent"] = USER_AGENT
        self._last_request_at = 0.0

    def _get(self, path: str) -> BeautifulSoup:
        wait = REQUEST_DELAY_SECONDS - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(f"{BASE_URL}{path}", timeout=30)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def bundesliga_teams(self) -> list[dict]:
        """Team names and page URLs from the Bundesliga table."""
        soup = self._get("/bundesliga/tabelle/")
        teams = []
        seen = set()
        table = soup.find("table") or soup
        for a in table.find_all("a", href=TEAM_HREF):
            href = a["href"]
            name = a.get_text(strip=True)
            if href in seen or not name:
                continue
            seen.add(href)
            teams.append({"name": name, "url": href})
        return teams

    def injuries(self) -> list[dict]:
        """All injured/suspended/doubtful players, grouped info per row."""
        soup = self._get("/bundesliga/verletzte-und-gesperrte-spieler/")
        rows = []
        for block in soup.find_all("div", class_="personal_table"):
            team_el = block.find("h2")
            team = team_el.get_text(strip=True) if team_el else "?"
            for row in block.find_all("div", class_="small_table_row"):
                cols = {
                    n: row.find("div", class_=f"small_table_column{n}")
                    for n in (1, 2, 3, 4)
                }
                if not cols[1]:
                    continue
                player_link = cols[1].find("a", href=PLAYER_HREF)
                icon = cols[1].find("img")
                news_link = cols[3].find("a") if cols[3] else None
                rows.append(
                    {
                        "team": team,
                        "player": player_link.get_text(strip=True) if player_link else "?",
                        "player_url": player_link["href"] if player_link else None,
                        "status": icon.get("alt") if icon else None,
                        "reason": cols[2].get_text(strip=True) if cols[2] else None,
                        "news_title": news_link.get_text(strip=True) if news_link else None,
                        "news_url": news_link["href"] if news_link else None,
                        "out_since": cols[4].get_text(strip=True) if cols[4] else None,
                    }
                )
        return rows

    def predicted_lineup(self, team_url: str) -> dict:
        """Predicted starting XI from a team page (stadium visualization)."""
        soup = self._get(team_url)
        result = {"team_url": team_url, "match": None, "players": []}

        match_el = soup.find("div", class_="team_box_right")
        if match_el and match_el.find("p"):
            result["match"] = match_el.find("p").get_text(" ", strip=True)

        pitch = soup.find("div", class_="stadium_container_bg")
        if not pitch:
            return result
        for column in pitch.find_all("div", class_="player_position_column"):
            name_el = column.find("div", class_="player_name")
            link = name_el.find("a", href=PLAYER_HREF) if name_el else None
            if not link:
                continue
            player = {
                "name": link.get_text(strip=True),
                "player_url": link["href"],
            }
            # "tags_boost" is Ligainsider's Kickbase-boost stat, NOT a start
            # probability — kept for reference only.
            boost = column.find("div", class_="tags_boost")
            if boost and boost.find("span"):
                player["boost_pct"] = boost.find("span").get_text(strip=True)
            result["players"].append(player)
        return result
