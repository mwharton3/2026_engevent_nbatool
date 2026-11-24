"""Find performance risers and judge whether the bump is likely to last.

Performance = Hollinger Game Score (GmSc) per game. A player's "surge" is
their average GmSc in the recent window minus their season-to-date baseline
(all games before the window).

The surge is split into a *minutes* component (baseline GmSc-per-minute x
extra minutes) and a *rate* component (doing more per minute). Each has a
different sustainability story:

* Minutes  -> why did minutes go up? We look for rotation teammates who missed
  window games and check whether they are still out (injury report + expected
  return date), gone (no longer on roster), or already back - and, if back,
  whether the player's minutes held up in the games since.
* Rate     -> is it a shooting heater (TS% spike, likely to regress) or a real
  usage/role change?
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Optional

from .model import InjuryEntry, League, PlayerGame

ROTATION_MPG = 15.0  # teammates below this aren't meaningful minute sources
MATERIAL_VACATED_MPG = 2.0  # absences that freed up fewer minutes than this are noise
MIN_TS_ATTEMPTS = (20.0, 10.0)  # (baseline, window) true-shot attempts needed to judge shooting luck


# --- aggregates ----------------------------------------------------------

@dataclass
class Split:
    games: int = 0
    mpg: float = 0.0
    gmsc: float = 0.0
    pts: float = 0.0
    reb: float = 0.0
    ast: float = 0.0
    stocks: float = 0.0
    ts: Optional[float] = None
    usage36: float = 0.0  # (FGA + 0.44 FTA + TOV) per 36 min - a box-score usage proxy
    tsa: float = 0.0  # total true-shot attempts (FGA + 0.44 FTA)
    start_rate: float = 0.0

    @property
    def gmsc_per_min(self) -> float:
        return self.gmsc / self.mpg if self.mpg else 0.0


def summarize(games: list[PlayerGame]) -> Split:
    played = [g for g in games if g.played]
    if not played:
        return Split()
    mins = sum(g.minutes for g in played)
    pts = sum(g.pts for g in played)
    tsa = sum(g.fga + 0.44 * g.fta for g in played)
    poss = sum(g.fga + 0.44 * g.fta + g.tov for g in played)
    return Split(
        games=len(played),
        mpg=mins / len(played),
        gmsc=mean(g.game_score for g in played),
        pts=pts / len(played),
        reb=mean(g.reb for g in played),
        ast=mean(g.ast for g in played),
        stocks=mean(g.stl + g.blk for g in played),
        ts=pts / (2 * tsa) if tsa else None,
        usage36=36 * poss / mins if mins else 0.0,
        start_rate=sum(g.starter for g in played) / len(played),
        tsa=tsa,
    )


# --- sustainability ------------------------------------------------------

@dataclass
class AbsentTeammate:
    name: str
    base_mpg: float
    missed: int
    of_games: int
    status: str  # departed | out-long | returning-soon | day-to-day | back | unknown
    detail: str
    player_mpg_with: Optional[float] = None  # player's window mpg in games this teammate played
    player_mpg_without: Optional[float] = None  # ...and in games this teammate missed

    @property
    def vacated_mpg(self) -> float:
        return self.base_mpg * self.missed / self.of_games

    @property
    def lasting(self) -> Optional[bool]:
        if self.status in ("departed", "out-long"):
            return True
        if self.status in ("returning-soon", "day-to-day", "back"):
            return False
        return None


@dataclass
class Signal:
    weight: float  # + supports sustained, - suggests fade
    text: str


@dataclass
class Riser:
    player_id: str
    name: str
    team: str
    position: str
    base: Split
    recent: Split
    recent_games: list[PlayerGame]
    minutes_effect: float
    rate_effect: float
    absences: list[AbsentTeammate] = field(default_factory=list)
    own_injury: Optional[InjuryEntry] = None
    signals: list[Signal] = field(default_factory=list)

    @property
    def delta(self) -> float:
        return self.recent.gmsc - self.base.gmsc

    @property
    def score(self) -> float:
        return sum(s.weight for s in self.signals)

    @property
    def verdict(self) -> str:
        if self.score >= 1.5:
            return "Likely sustained"
        if self.score <= -1.5:
            return "Likely to fade"
        return "Toss-up"

    @property
    def confidence(self) -> str:
        if self.recent.games <= 2 or self.base.games < 6:
            return "low"
        if abs(self.score) >= 3 and self.recent.games >= 3:
            return "high"
        return "medium"


def _classify_absence(pid: str, team: str, league: League, end: date,
                      back_since: Optional[date]) -> tuple[str, str]:
    inj = league.injuries.get(pid)
    roster = league.rosters.get(team)
    if roster is not None and pid not in roster:
        return "departed", "no longer on roster"
    if inj:
        rd = inj.return_date
        what = f"{inj.status}" + (f" ({inj.injury})" if inj.injury else "")
        if inj.status.lower().startswith("out"):
            if rd is None or rd > end + timedelta(days=10):
                return "out-long", what + (f", est. return {rd:%b %d}" if rd else ", no return date")
            return "returning-soon", what + f", est. return {rd:%b %d}"
        return "day-to-day", what + (f", est. return {rd:%b %d}" if rd else "")
    if back_since:
        return "back", f"back since {back_since:%b %d}"
    return "unknown", "not on injury report"


def find_absences(player_id: str, team: str, league: League, window_start: date, end: date,
                  by_player: dict[str, list[PlayerGame]]) -> list[AbsentTeammate]:
    team_window = sorted(
        {tg.game_id: tg for tg in league.team_games
         if tg.team == team and window_start <= tg.game_date <= end}.values(),
        key=lambda tg: tg.game_date,
    )
    if not team_window:
        return []
    window_ids = {tg.game_id for tg in team_window}

    player_window = {g.game_id: g for g in by_player[player_id]
                     if g.game_id in window_ids and g.played}

    out: list[AbsentTeammate] = []
    for pid, games in by_player.items():
        if pid == player_id:
            continue
        on_team = [g for g in games if g.team == team]
        if not on_team:
            continue
        base = [g for g in on_team if g.game_date < window_start and g.played]
        if len(base) < 3:
            continue
        base_mpg = mean(g.minutes for g in base)
        if base_mpg < ROTATION_MPG:
            continue
        played_ids = {g.game_id for g in on_team if g.played}
        missed = [gid for gid in window_ids if gid not in played_ids]
        if not missed:
            continue
        # "Back" = played the team's latest game; report when the current run of games started.
        back_since = None
        for tg in reversed(team_window):
            if tg.game_id not in played_ids:
                break
            back_since = tg.game_date
        status, detail = _classify_absence(pid, team, league, end, back_since)
        with_ids = [gid for gid in window_ids if gid in played_ids and gid in player_window]
        without_ids = [gid for gid in missed if gid in player_window]
        out.append(AbsentTeammate(
            name=on_team[-1].name, base_mpg=base_mpg, missed=len(missed), of_games=len(window_ids),
            status=status, detail=detail,
            player_mpg_with=mean(player_window[g].minutes for g in with_ids) if with_ids else None,
            player_mpg_without=mean(player_window[g].minutes for g in without_ids) if without_ids else None,
        ))
    out.sort(key=lambda a: -a.vacated_mpg)
    return out


def _names(absences: list[AbsentTeammate], limit: int = 3) -> str:
    shown = ", ".join(f"{a.name} ({a.detail})" for a in absences[:limit])
    return shown + (f" +{len(absences) - limit} more" if len(absences) > limit else "")


def assess(r: Riser) -> None:
    """Populate r.signals with weighted reasons for/against sustainability."""
    sig = r.signals
    min_delta = r.recent.mpg - r.base.mpg
    gain = max(r.delta, 1e-9)
    minutes_share = max(0.0, min(1.0, r.minutes_effect / gain))

    # 1) Minutes: why did they go up?
    if min_delta >= 3:
        w = 1.0 + minutes_share  # extra minutes usually also bring a bigger role, so weigh them fully
        material = [a for a in r.absences if a.vacated_mpg >= MATERIAL_VACATED_MPG]

        # A teammate already came back: did the player keep the minutes alongside them?
        held_up = [a for a in material if a.status == "back" and a.player_mpg_with is not None
                   and a.player_mpg_with >= r.base.mpg + 0.6 * min_delta]
        if held_up:
            a = held_up[0]
            without = f", {a.player_mpg_without:.0f} without" if a.player_mpg_without is not None else ""
            sig.append(Signal(+1.0 * w, f"Minutes held up with {a.name} back ({a.player_mpg_with:.0f} mpg "
                              f"alongside{without}; {r.base.mpg:.0f} baseline)"))
        rest = [a for a in material if a not in held_up]
        lasting = [a for a in rest if a.lasting is True]
        temporary = [a for a in rest if a.lasting is False]
        lasting_mpg = sum(a.vacated_mpg for a in lasting)
        temp_mpg = sum(a.vacated_mpg for a in temporary)

        if temporary and temp_mpg >= max(lasting_mpg, 0.5 * min_delta):
            sig.append(Signal(-1.5 * w, f"Extra minutes (+{min_delta:.1f}) tied to short-term absences: "
                              + _names(temporary)))
        elif lasting and lasting_mpg >= 0.5 * min_delta:
            sig.append(Signal(+1.5 * w, f"Extra minutes (+{min_delta:.1f}) backed by long-term absences: "
                              + _names(lasting)))
        elif not held_up:
            if r.recent.start_rate >= 0.5 > r.base.start_rate:
                sig.append(Signal(+1.0 * w, f"Promoted to the starting lineup (+{min_delta:.1f} mpg) "
                                  "without an injury-driven cause"))
            else:
                sig.append(Signal(+0.5 * w, f"Rotation role expanded (+{min_delta:.1f} mpg) "
                                  "with no obvious injury cause"))

    # 2) Rate: shooting luck vs. role
    rate_share = 1 - minutes_share
    enough_shots = r.base.tsa >= MIN_TS_ATTEMPTS[0] and r.recent.tsa >= MIN_TS_ATTEMPTS[1]
    if enough_shots and r.recent.ts is not None and r.base.ts is not None:
        ts_delta = r.recent.ts - r.base.ts
        if ts_delta >= 0.08:
            sig.append(Signal(-1.0 - rate_share, f"Shooting heater: TS% {r.recent.ts:.1%} vs {r.base.ts:.1%} "
                              "baseline - expect regression"))
        elif ts_delta >= 0.04 and rate_share > 0.4:
            sig.append(Signal(-0.5, f"Efficiency up (TS% {r.recent.ts:.1%} vs {r.base.ts:.1%}) - partly unsustainable"))
        elif ts_delta < 0.04 and rate_share > 0.4:
            sig.append(Signal(+0.75, f"Per-minute gain isn't shooting luck (TS% {r.recent.ts:.1%} "
                              f"vs {r.base.ts:.1%})"))
    usage_delta = r.recent.usage36 - r.base.usage36
    if usage_delta >= 3 and rate_share > 0.3:
        temp = any(a.lasting is False and a.vacated_mpg >= MATERIAL_VACATED_MPG for a in r.absences)
        if temp:
            sig.append(Signal(-0.5, f"Usage up {usage_delta:+.1f}/36 while a teammate was out"))
        else:
            sig.append(Signal(+0.5, f"Bigger offensive role: usage {usage_delta:+.1f}/36"))

    # 3) The player's own availability
    if r.own_injury:
        inj = r.own_injury
        status = inj.status.lower()
        rd = f", est. return {inj.return_date:%b %d}" if inj.return_date else ""
        if status.startswith("out"):
            long_term = inj.return_date is None or inj.return_date > r.recent_games[-1].game_date + timedelta(days=10)
            sig.append(Signal(-3.0 if long_term else -2.0, f"Currently out{f' ({inj.injury})' if inj.injury else ''}{rd}"))
        else:
            sig.append(Signal(-0.5, f"Currently on injury report: {inj.status}{rd}"))

    # 4) Workload / sample size
    if r.recent.mpg >= 37:
        sig.append(Signal(-0.5, f"Heavy workload ({r.recent.mpg:.0f} mpg) is hard to maintain"))
    if r.recent.games <= 2:
        sig.append(Signal(-0.5, f"Tiny sample: {r.recent.games} games this week"))


# --- driver --------------------------------------------------------------

def find_risers(league: League, end: date, window_days: int = 7, min_recent_games: int = 2,
                min_base_games: int = 4, min_recent_mpg: float = 12.0, top: int = 25) -> list[Riser]:
    window_start = end - timedelta(days=window_days - 1)
    by_player: dict[str, list[PlayerGame]] = defaultdict(list)
    for g in league.games:
        if g.game_date <= end:
            by_player[g.player_id].append(g)
    for games in by_player.values():
        games.sort(key=lambda g: g.game_date)

    risers: list[Riser] = []
    for pid, games in by_player.items():
        recent_games = [g for g in games if g.game_date >= window_start and g.played]
        base = summarize([g for g in games if g.game_date < window_start])
        recent = summarize(recent_games)
        if recent.games < min_recent_games or base.games < min_base_games or recent.mpg < min_recent_mpg:
            continue
        if recent.gmsc <= base.gmsc:
            continue
        latest = games[-1]
        rate = max(base.gmsc_per_min, 0.0)
        minutes_effect = rate * (recent.mpg - base.mpg)
        risers.append(Riser(
            player_id=pid, name=latest.name, team=latest.team, position=latest.position,
            base=base, recent=recent, recent_games=recent_games,
            minutes_effect=minutes_effect, rate_effect=(recent.gmsc - base.gmsc) - minutes_effect,
        ))

    risers.sort(key=lambda r: -r.delta)
    risers = risers[:top]
    for r in risers:
        r.absences = find_absences(r.player_id, r.team, league, window_start, end, by_player)
        r.own_injury = league.injuries.get(r.player_id)
        assess(r)
    return risers
