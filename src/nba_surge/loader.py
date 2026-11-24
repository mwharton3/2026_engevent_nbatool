"""Assemble a League from ESPN data for a date range."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from .espn import EspnClient
from .model import League, parse_injuries, parse_roster, parse_summary

REGULAR_SEASON = 2


def load_league(client: EspnClient, start: date, end: date, include_postseason: bool = False) -> League:
    days = [start + timedelta(d) for d in range((end - start).days + 1)]
    print(f"Loading scoreboards {start} → {end} ({len(days)} days)…", file=sys.stderr)
    boards = client.scoreboards(days)

    event_days: list[tuple[str, date]] = []
    for day, board in zip(days, boards):
        for ev in board.get("events", []):
            stype = (ev.get("season") or {}).get("type")
            if stype != REGULAR_SEASON and not (include_postseason and stype == 3):
                continue
            if not ev["status"]["type"].get("completed"):
                continue
            # Use the scoreboard's US calendar day, not the UTC tip-off timestamp.
            event_days.append((str(ev["id"]), day))

    print(f"Loading {len(event_days)} box scores (cached after first run)…", file=sys.stderr)
    summaries = client.summaries([eid for eid, _ in event_days])

    league = League()
    for (_, day), summ in zip(event_days, summaries):
        players, teams = parse_summary(summ, day)
        league.games.extend(players)
        league.team_games.extend(teams)
        for t in teams:
            league.team_ids[t.team] = t.team_id

    print("Loading injury report and rosters…", file=sys.stderr)
    league.injuries = parse_injuries(client.injuries())
    rosters = client.rosters(sorted(set(league.team_ids.values())))
    abbr_by_id = {v: k for k, v in league.team_ids.items()}
    league.rosters = {abbr_by_id[tid]: parse_roster(r) for tid, r in rosters.items()}
    return league


def default_end(today: date | None = None) -> date:
    """Most recent fully completed slate: yesterday (US time)."""
    today = today or datetime.now().date()
    return today - timedelta(days=1)
