"""Thin client for ESPN's public NBA JSON API, with an on-disk cache.

Completed games and past scoreboards never change, so they are cached forever.
Injury reports and rosters change daily, so they expire after a short TTL.
"""

from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DEFAULT_CACHE = Path.home() / ".cache" / "nba_surge"
VOLATILE_TTL_S = 60 * 60  # injuries / rosters


class EspnClient:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE, workers: int = 8, verbose: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.workers = workers
        self.verbose = verbose

    # -- low level -------------------------------------------------------
    def _get(self, url: str, retries: int = 3) -> dict:
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "nba-surge/0.1"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # network hiccups, 5xx, bad JSON
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")

    def _cached(self, key: str, url: str, ttl_s: Optional[int], keep) -> dict:
        """Fetch `url`, caching to `key`. ttl_s=None means cache forever,
        but only once `keep(data)` says the payload is final."""
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            fresh = ttl_s is None or (time.time() - path.stat().st_mtime) < ttl_s
            if fresh:
                return json.loads(path.read_text())
        if self.verbose:
            print(f"  fetch {url}")
        data = self._get(url)
        if keep(data):
            path.write_text(json.dumps(data))
        return data

    # -- endpoints -------------------------------------------------------
    def scoreboard(self, day: date) -> dict:
        ymd = day.strftime("%Y%m%d")

        def is_final(d: dict) -> bool:
            events = d.get("events") or []
            if not events:  # off-day: final once the day has passed
                return day < date.today()
            return all(e["status"]["type"].get("completed") for e in events)

        return self._cached(f"scoreboard_{ymd}", f"{BASE}/scoreboard?dates={ymd}", None, is_final)

    def summary(self, event_id: str) -> dict:
        final = lambda d: d.get("header", {}).get("competitions", [{}])[0].get(  # noqa: E731
            "status", {}
        ).get("type", {}).get("completed", False)
        return self._cached(f"summary_{event_id}", f"{BASE}/summary?event={event_id}", None, final)

    def injuries(self) -> dict:
        return self._cached("injuries", f"{BASE}/injuries", VOLATILE_TTL_S, lambda d: True)

    def roster(self, team_id: str) -> dict:
        return self._cached(f"roster_{team_id}", f"{BASE}/teams/{team_id}/roster", VOLATILE_TTL_S, lambda d: True)

    # -- bulk helpers ----------------------------------------------------
    def scoreboards(self, days: Iterable[date]) -> list[dict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self.scoreboard, days))

    def summaries(self, event_ids: Iterable[str]) -> list[dict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self.summary, event_ids))

    def rosters(self, team_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(team_ids)
        with ThreadPoolExecutor(self.workers) as pool:
            return dict(zip(ids, pool.map(self.roster, ids)))
