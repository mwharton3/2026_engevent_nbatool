"""Command-line entry point: `nba-surge` / `python -m nba_surge`."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .analysis import find_risers
from .espn import DEFAULT_CACHE, EspnClient
from .loader import default_end, load_league
from .report import render_html, render_text

SEASON_START = date(2026, 10, 20)  # 2026-27 regular season tip-off


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="NBA players with the biggest performance jump in the past week, "
                                             "and whether it's likely to last.")
    ap.add_argument("--end", type=date.fromisoformat, default=None,
                    help="last day of the window (YYYY-MM-DD; default: yesterday)")
    ap.add_argument("--days", type=int, default=7, help="window length in days (default 7)")
    ap.add_argument("--season-start", type=date.fromisoformat, default=SEASON_START)
    ap.add_argument("--top", type=int, default=20, help="how many risers to show")
    ap.add_argument("--min-games", type=int, default=2, help="min games played in the window")
    ap.add_argument("--min-base-games", type=int, default=4, help="min games before the window")
    ap.add_argument("--min-mpg", type=float, default=12.0, help="min minutes per game in the window")
    ap.add_argument("--html", type=Path, default=Path("nba_risers.html"), help="write HTML report here")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--json", type=Path, help="also dump results as JSON")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("-v", "--verbose", action="store_true", help="show every reason, log fetches")
    args = ap.parse_args(argv)

    end = args.end or default_end()
    window_start = end - timedelta(days=args.days - 1)
    client = EspnClient(args.cache_dir, verbose=args.verbose)
    league = load_league(client, args.season_start, end)

    risers = find_risers(league, end, window_days=args.days, min_recent_games=args.min_games,
                         min_base_games=args.min_base_games, min_recent_mpg=args.min_mpg, top=args.top)

    print(render_text(risers, window_start, end, verbose=args.verbose))

    if not args.no_html:
        by_player = defaultdict(list)
        for g in sorted(league.games, key=lambda g: g.game_date):
            if g.game_date <= end:
                by_player[g.player_id].append(g)
        generated = datetime.now().strftime("%b %d, %Y %H:%M")
        args.html.write_text(render_html(risers, by_player, window_start, end, generated))
        print(f"\nHTML report: {args.html.resolve()}")

    if args.json:
        args.json.write_text(json.dumps([{
            "name": r.name, "team": r.team, "delta_gmsc": round(r.delta, 2), "verdict": r.verdict,
            "confidence": r.confidence, "base_gmsc": round(r.base.gmsc, 2), "recent_gmsc": round(r.recent.gmsc, 2),
            "base_mpg": round(r.base.mpg, 1), "recent_mpg": round(r.recent.mpg, 1),
            "reasons": [s.text for s in r.signals],
        } for r in risers], indent=2))


if __name__ == "__main__":
    main()
