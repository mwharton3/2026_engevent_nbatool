# nba-surge

Find the NBA players whose performance jumped the most in the past week, and judge whether that output is likely to last given minute allocation and player availability.

```bash
uv run nba-surge                 # last 7 days ending yesterday → terminal table + nba_risers.html
uv run nba-surge -v              # every reason, plus fetch logging
uv run nba-surge --end 2026-11-16 --top 30 --json risers.json
```

No API key needed. Data comes from ESPN's public JSON API (box scores, the league injury report, and team rosters). Box scores are cached in `~/.cache/nba_surge`, so the first run takes about 20s and later runs take about 1s.

## How it works

**Performance.** Each game is scored with [Hollinger Game Score](https://www.basketball-reference.com/about/glossary.html#gmsc). A player's surge (Δ) is their average over the last 7 days minus their average for every earlier game this season. To qualify, a player needs at least 2 games in the window, at least 4 games before it, and at least 12 minutes per game in the window.

**Where the gain came from.** The tool splits Δ into two parts:
- **minutes:** baseline Game Score per minute × the extra minutes
- **per-minute:** everything else

**Sustainability.** The outlook is a weighted vote of these signals:

| Signal | Effect |
|---|---|
| Extra minutes line up with rotation teammates (≥15 mpg) who missed window games and are **out long-term** (expected return >10 days away, or no date) or **no longer on the roster** | ▲ sustain |
| …or with teammates who are **day-to-day / returning within ~10 days**, or who are already **back** | ▼ fade |
| A teammate is already back and the player **kept the minutes** in the games played alongside them | ▲ sustain |
| More minutes or a new starting role with **no injury cause** (coach's choice) | ▲ sustain |
| **TS% spike** (+8 pts or more) compared with baseline: a shooting heater | ▼ fade |
| Per-minute gain **without** a TS% spike (a real role or usage change) | ▲ sustain |
| Usage up only while a teammate was out | ▼ fade |
| Player is **on the injury report** (worse if out long-term) | ▼ fade |
| Workload of 37+ mpg, or only 2 games of sample | ▼ fade (slight) |

The outlook is **Likely sustained** when the score is ≥ 1.5, **Likely to fade** when it is ≤ −1.5, and **Toss-up** in between. Confidence drops when the sample is small.

## Development

```bash
uv run --extra dev pytest
```

Code layout (`src/nba_surge/`):
- `espn.py`: HTTP client and cache
- `model.py`: parsing
- `loader.py`: assembles the season
- `analysis.py`: risers and the sustainability logic
- `report.py`: terminal and HTML output
- `cli.py`: command-line entry point

## Limitations

- "Teammate absent" means the teammate didn't log minutes. The tool doesn't use lineup or position matching, so it assumes freed-up minutes go to whoever's minutes rose.
- Expected return dates come from ESPN's injury feed and can be stale or missing.
- `--season-start` defaults to the 2026-27 opener (Oct 20, 2026). Change it for other seasons.
