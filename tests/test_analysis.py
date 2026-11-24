from datetime import date, timedelta

from nba_surge.analysis import find_risers, summarize
from nba_surge.model import InjuryEntry, League, PlayerGame, TeamGame, parse_summary

END = date(2026, 11, 23)
WINDOW_START = END - timedelta(days=6)


def pg(pid, day, minutes, pts, fga=None, fgm=None, team="AAA", starter=False, played=True):
    fga = fga if fga is not None else max(1, pts // 2)
    fgm = fgm if fgm is not None else pts // 2
    return PlayerGame(player_id=pid, name=f"P{pid}", team=team, team_id="1", position="G",
                      game_id=f"g{day.isoformat()}", game_date=day, starter=starter, played=played,
                      minutes=minutes if played else 0, pts=pts if played else 0,
                      fga=fga if played else 0, fgm=fgm if played else 0)


def build(star_status=None, star_return=None, star_back=False, hot_shooting=False, star_on_roster=True):
    """Team AAA: role player '1' (20 mpg) and star '2' (34 mpg). Star misses window games."""
    league = League()
    base_days = [WINDOW_START - timedelta(days=2 * i + 1) for i in range(8)]
    win_days = [WINDOW_START + timedelta(days=i) for i in (0, 2, 4, 6)]
    for d in base_days:
        league.games += [pg("1", d, 20, 8, fga=8, fgm=3), pg("2", d, 34, 25, starter=True)]
    for i, d in enumerate(win_days):
        star_plays = star_back and i == len(win_days) - 1
        if hot_shooting:
            league.games.append(pg("1", d, 20, 22, fga=12, fgm=9))
        else:
            league.games.append(pg("1", d, 34, 20, fga=18, fgm=7, starter=True))
        league.games.append(pg("2", d, 34, 25, starter=True, played=star_plays))
    for d in base_days + win_days:
        league.team_games.append(TeamGame(f"g{d.isoformat()}", d, "AAA", "1"))
    league.rosters = {"AAA": {"1", "2"} if star_on_roster else {"1"}}
    if star_status:
        league.injuries["2"] = InjuryEntry("2", "P2", "AAA", star_status, star_return, "", "Knee")
    return league


def riser(league):
    rs = find_risers(league, END)
    assert rs and rs[0].player_id == "1"
    return rs[0]


def test_game_score_formula():
    g = PlayerGame("1", "x", "A", "1", "G", "g", END, True, True, minutes=30, pts=20, fgm=8, fga=15,
                   ftm=4, fta=5, oreb=1, dreb=5, ast=6, stl=2, blk=1, tov=3, pf=2)
    expected = 20 + 0.4 * 8 - 0.7 * 15 - 0.4 * 1 + 0.7 * 1 + 0.3 * 5 + 2 + 0.7 * 6 + 0.7 * 1 - 0.4 * 2 - 3
    assert abs(g.game_score - expected) < 1e-9


def test_summarize_ignores_dnp():
    s = summarize([pg("1", END, 30, 10), pg("1", END, 0, 0, played=False)])
    assert s.games == 1 and s.mpg == 30


def test_long_term_injury_means_sustained():
    r = riser(build(star_status="Out", star_return=END + timedelta(days=40)))
    assert r.verdict == "Likely sustained"
    assert any("long-term" in s.text for s in r.signals)


def test_short_term_injury_means_fade():
    r = riser(build(star_status="Out", star_return=END + timedelta(days=3)))
    assert r.verdict == "Likely to fade"
    assert any("short-term" in s.text for s in r.signals)


def test_departed_teammate_counts_as_lasting():
    r = riser(build(star_on_roster=False))
    assert r.absences[0].status == "departed"
    assert r.verdict == "Likely sustained"


def test_teammate_back_and_minutes_held_up():
    r = riser(build(star_back=True))
    assert r.absences[0].status == "back"
    assert any("held up" in s.text for s in r.signals)


def test_shooting_heater_flags_regression():
    r = riser(build(hot_shooting=True))
    assert r.minutes_effect == 0
    assert any("heater" in s.text for s in r.signals)
    assert r.verdict == "Likely to fade"


def test_parse_summary_minimal():
    summary = {"header": {"id": "9"}, "boxscore": {"players": [{
        "team": {"abbreviation": "AAA", "id": "1"},
        "statistics": [{
            "keys": ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted", "rebounds"],
            "athletes": [
                {"athlete": {"id": "5", "displayName": "A"}, "starter": True, "stats": ["31", "20", "8-15", "7"]},
                {"athlete": {"id": "6", "displayName": "B"}, "didNotPlay": True, "reason": "COACH'S DECISION", "stats": []},
            ]}]}]}}
    players, teams = parse_summary(summary, END)
    a, b = players
    assert a.played and a.minutes == 31 and (a.fgm, a.fga) == (8, 15) and a.reb == 7
    assert not b.played and b.dnp_reason == "COACH'S DECISION"
    assert teams[0].team == "AAA"
