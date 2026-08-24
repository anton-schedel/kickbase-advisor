"""Minimal client for the unofficial Kickbase v4 API.

Community docs: https://github.com/kevinskyba/kickbase-api-doc
"""

import time

import requests

BASE_URL = "https://api.kickbase.com"

# Delay between requests so we behave like a normal app user, not a crawler.
REQUEST_DELAY_SECONDS = 0.5


class KickbaseError(Exception):
    pass


class KickbaseClient:
    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._token: str | None = None
        self._last_request_at = 0.0
        self.user: dict | None = None

    def login(self) -> dict:
        resp = self._session.post(
            f"{BASE_URL}/v4/user/login",
            json={"em": self._email, "pass": self._password, "loy": False, "rep": {}},
            timeout=30,
        )
        if resp.status_code == 401:
            raise KickbaseError("Login failed: wrong email or password (401).")
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("tkn")
        if not self._token:
            raise KickbaseError(f"Login response had no token. Keys: {list(data.keys())}")
        self._session.headers["Authorization"] = f"Bearer {self._token}"
        self.user = data.get("u")
        return data

    def get(self, path: str, params: dict | None = None) -> dict:
        if not self._token:
            raise KickbaseError("Not logged in — call login() first.")
        wait = REQUEST_DELAY_SECONDS - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(f"{BASE_URL}{path}", params=params, timeout=30)
        self._last_request_at = time.monotonic()
        if resp.status_code == 401:
            raise KickbaseError(f"Token rejected on {path} (401) — session expired?")
        resp.raise_for_status()
        return resp.json()

    # --- convenience wrappers for the endpoints we use ---

    def leagues(self) -> dict:
        return self.get("/v4/leagues/selection")

    def league_overview(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/overview")

    def league_me(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/me")

    def league_budget(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/me/budget")

    def league_ranking(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/ranking")

    def squad(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/squad")

    def market(self, league_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/market")

    def player_market_value(self, league_id: str, player_id: str, timeframe: int = 365) -> dict:
        return self.get(f"/v4/leagues/{league_id}/players/{player_id}/marketValue/{timeframe}")

    def player_performance(self, league_id: str, player_id: str) -> dict:
        return self.get(f"/v4/leagues/{league_id}/players/{player_id}/performance")
