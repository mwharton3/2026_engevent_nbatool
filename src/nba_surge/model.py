"""Plain data records parsed out of ESPN payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class PlayerGame:
    player_id: str
    name: str
    team: str  # abbreviation, e.g. "ATL"
    team_id: str
    position: str
    game_id: str
    game_date: date
    starter: bool
    played: bool  # False for DNP / inactive rows
    dnp_reason: str = ""
    minutes: float = 0.0
    pts: int = 0
    fgm: int = 0
    fga: int = 0
    tpm: int = 0
    tpa: int = 0
    ftm: int = 0
    fta: int = 0
    oreb: int = 0
    dreb: int = 0
    reb: int = 0
    ast: int = 0
    stl: int = 0
    blk: int = 0
    tov: int = 0
    pf: int = 0

    @property
    def game_score(self) -> float:
        """John Hollinger's Game Score: a single-number box-score production metric."""
        return (
            self.pts + 0.4 * self.fgm - 0.7 * self.fga - 0.4 * (self.fta - self.ftm)
            + 0.7 * self.oreb + 0.3 * self.dreb + self.stl + 0.7 * self.ast
            + 0.7 * self.blk - 0.4 * self.pf - self.tov
        )


@dataclass
class TeamGame:
    game_id: str
    game_date: date
    team: str
    team_id: str


@dataclass
class InjuryEntry:
    player_id: str
    name: str
    team: str
    status: str  # "Out", "Day-To-Day", ...
    return_date: Optional[date]
    note: str
    injury: str


@dataclass
class League:
    """Everything the analysis needs, in one bundle."""

    games: list[PlayerGame] = field(default_factory=list)
    team_games: list[TeamGame] = field(default_factory=list)
    injuries: dict[str, InjuryEntry] = field(default_factory=dict)  # by player_id
    rosters: dict[str, set[str]] = field(default_factory=dict)  # team abbr -> player ids
    team_ids: dict[str, str] = field(default_factory=dict)  # team abbr -> espn team id


# --- parsing -------------------------------------------------------------

def _split(made_att: str) -> tuple[int, int]:
    try:
        m, a = made_att.split("-")
        return int(m), int(a)
    except ValueError:
        return 0, 0


def _int(s: str) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def _minutes(s: str) -> float:
    if not s:
        return 0.0
    if ":" in s:
        m, sec = s.split(":")
        return _int(m) + _int(sec) / 60
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_summary(summary: dict, game_date: date) -> tuple[list[PlayerGame], list[TeamGame]]:
    game_id = str(summary["header"]["id"])
    players: list[PlayerGame] = []
    teams: list[TeamGame] = []
    for team_block in summary.get("boxscore", {}).get("players", []):
        team = team_block["team"]["abbreviation"]
        team_id = str(team_block["team"]["id"])
        teams.append(TeamGame(game_id, game_date, team, team_id))
        for stat_group in team_block.get("statistics", []):
            keys = stat_group.get("keys") or []
            for row in stat_group.get("athletes", []):
                ath = row["athlete"]
                stats = row.get("stats") or []
                pos = (ath.get("position") or {}).get("abbreviation", "")
                pg = PlayerGame(
                    player_id=str(ath["id"]), name=ath["displayName"], team=team, team_id=team_id,
                    position=pos, game_id=game_id, game_date=game_date,
                    starter=bool(row.get("starter")),
                    played=bool(stats) and not row.get("didNotPlay"),
                    dnp_reason=(row.get("reason") or "") if not stats or row.get("didNotPlay") else "",
                )
                if pg.played:
                    v = dict(zip(keys, stats))
                    pg.minutes = _minutes(v.get("minutes", "0"))
                    pg.pts = _int(v.get("points"))
                    pg.fgm, pg.fga = _split(v.get("fieldGoalsMade-fieldGoalsAttempted", "0-0"))
                    pg.tpm, pg.tpa = _split(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0"))
                    pg.ftm, pg.fta = _split(v.get("freeThrowsMade-freeThrowsAttempted", "0-0"))
                    pg.oreb = _int(v.get("offensiveRebounds"))
                    pg.dreb = _int(v.get("defensiveRebounds"))
                    pg.reb = _int(v.get("rebounds"))
                    pg.ast = _int(v.get("assists"))
                    pg.stl = _int(v.get("steals"))
                    pg.blk = _int(v.get("blocks"))
                    pg.tov = _int(v.get("turnovers"))
                    pg.pf = _int(v.get("fouls"))
                    if pg.minutes <= 0:
                        pg.played = False
                players.append(pg)
    return players, teams


_ID_RE = re.compile(r"/id/(\d+)")


def parse_injuries(payload: dict) -> dict[str, InjuryEntry]:
    out: dict[str, InjuryEntry] = {}
    for team_block in payload.get("injuries", []):
        for inj in team_block.get("injuries", []):
            ath = inj.get("athlete", {})
            pid = None
            for link in ath.get("links", []):
                m = _ID_RE.search(link.get("href", ""))
                if m:
                    pid = m.group(1)
                    break
            if not pid:
                continue
            details = inj.get("details") or {}
            rd = details.get("returnDate")
            out[pid] = InjuryEntry(
                player_id=pid,
                name=ath.get("displayName", ""),
                team=team_block.get("displayName", ""),
                status=inj.get("status", ""),
                return_date=date.fromisoformat(rd[:10]) if rd else None,
                note=inj.get("shortComment", ""),
                injury=" ".join(x for x in (details.get("side"), details.get("type"), details.get("detail")) if x and x != "Not Specified"),
            )
    return out


def parse_roster(payload: dict) -> set[str]:
    return {str(a["id"]) for a in payload.get("athletes", [])}
