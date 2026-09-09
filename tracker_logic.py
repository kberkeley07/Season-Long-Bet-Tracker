from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

REGULAR_SEASON_GAMES = 17

STAT_OPTIONS = {
    "Passing Yards": ("passing_yards",),
    "Rushing Yards": ("rushing_yards",),
    "Receiving Yards": ("receiving_yards",),
    "Pass + Rush Yards": ("passing_yards", "rushing_yards"),
    "Rush + Receiving Yards": ("rushing_yards", "receiving_yards"),
    "Receptions": ("receptions",),
    "Passing TDs": ("passing_tds",),
    "Rushing TDs": ("rushing_tds",),
    "Receiving TDs": ("receiving_tds",),
    "Rush + Receiving TDs": ("rushing_tds", "receiving_tds"),
    "Interceptions Thrown": ("interceptions",),
    "Completions": ("completions",),
    "Pass Attempts": ("attempts",),
    "Carries": ("carries",),
    "Targets": ("targets",),
}

REQUIRED_BET_COLUMNS = [
    "player_name",
    "stat",
    "side",
    "line",
    "odds",
    "stake",
    "sportsbook",
    "notes",
]


def american_profit(stake: float, odds: int | float) -> float:
    stake = float(stake or 0)
    odds = float(odds or 0)
    if stake <= 0 or odds == 0:
        return 0.0
    if odds > 0:
        return stake * odds / 100
    return stake * 100 / abs(odds)


def normalize_bets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in REQUIRED_BET_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in {"player_name", "stat", "side", "sportsbook", "notes"} else 0
    out = out[REQUIRED_BET_COLUMNS]
    out["player_name"] = out["player_name"].fillna("").astype(str).str.strip()
    out["stat"] = out["stat"].fillna("").astype(str).str.strip()
    out["side"] = out["side"].fillna("Over").astype(str).str.title()
    out["line"] = pd.to_numeric(out["line"], errors="coerce").fillna(0.0)
    out["odds"] = pd.to_numeric(out["odds"], errors="coerce").fillna(-110).astype(int)
    out["stake"] = pd.to_numeric(out["stake"], errors="coerce").fillna(0.0)
    out["sportsbook"] = out["sportsbook"].fillna("").astype(str)
    out["notes"] = out["notes"].fillna("").astype(str)
    out = out[out["player_name"].ne("") & out["stat"].isin(STAT_OPTIONS)]
    out = out[out["side"].isin(["Over", "Under"])]
    return out.reset_index(drop=True)


def _name_column(stats: pd.DataFrame) -> str | None:
    for candidate in ("player_display_name", "player_name"):
        if candidate in stats.columns:
            return candidate
    return None


def find_player_rows(stats: pd.DataFrame, player_name: str) -> pd.DataFrame:
    if stats.empty:
        return stats.copy()
    name_col = _name_column(stats)
    if name_col is None:
        return stats.iloc[0:0].copy()
    needle = player_name.strip().casefold()
    names = stats[name_col].fillna("").astype(str).str.strip().str.casefold()
    exact = stats.loc[names.eq(needle)]
    if not exact.empty:
        return exact.copy()
    # Friendly fallback for formats like "J.Daniels" vs "Jayden Daniels".
    contains = stats.loc[names.str.contains(needle, regex=False)]
    if len(contains[_name_column(contains)].drop_duplicates()) == 1 if not contains.empty else False:
        return contains.copy()
    return stats.iloc[0:0].copy()


def current_stat(player_rows: pd.DataFrame, stat_label: str) -> float:
    if player_rows.empty or stat_label not in STAT_OPTIONS:
        return 0.0
    total = 0.0
    for col in STAT_OPTIONS[stat_label]:
        if col in player_rows.columns:
            total += pd.to_numeric(player_rows[col], errors="coerce").fillna(0).sum()
    return float(total)


def _team_column(stats: pd.DataFrame) -> str | None:
    # nflverse weekly player files use `team`; older/sibling datasets may use `recent_team`.
    for candidate in ("team", "recent_team"):
        if candidate in stats.columns:
            return candidate
    return None


def latest_team(player_rows: pd.DataFrame) -> str | None:
    if player_rows.empty:
        return None
    team_col = _team_column(player_rows)
    if team_col is None:
        return None
    rows = player_rows.copy()
    if "week" in rows.columns:
        rows["week"] = pd.to_numeric(rows["week"], errors="coerce")
        rows = rows.sort_values("week")
    teams = rows[team_col].dropna().astype(str)
    return teams.iloc[-1] if not teams.empty else None


def team_games_completed(stats: pd.DataFrame, team: str | None) -> int:
    team_col = _team_column(stats)
    if stats.empty or not team or team_col is None or "week" not in stats.columns:
        return 0
    team_rows = stats.loc[stats[team_col].astype(str).eq(team)]
    weeks = pd.to_numeric(team_rows["week"], errors="coerce").dropna().astype(int)
    return int(weeks.nunique())


def player_games_with_stats(player_rows: pd.DataFrame) -> int:
    if player_rows.empty or "week" not in player_rows.columns:
        return 0
    return int(pd.to_numeric(player_rows["week"], errors="coerce").dropna().astype(int).nunique())


def status_for_bet(side: str, line: float, projected: float, games_completed: int) -> tuple[str, str]:
    if games_completed <= 0:
        return "Not started", "⚪"
    # A 5% buffer avoids labeling tiny pace differences as strong signals.
    buffer = max(abs(line) * 0.05, 1.0)
    if side == "Over":
        if projected >= line + buffer:
            return "On pace", "🟢"
        if projected >= line - buffer:
            return "Sweat", "🟡"
        return "Off pace", "🔴"
    if projected <= line - buffer:
        return "On pace", "🟢"
    if projected <= line + buffer:
        return "Sweat", "🟡"
    return "Off pace", "🔴"


def evaluate_bet(bet: pd.Series, stats: pd.DataFrame, season_games: int = REGULAR_SEASON_GAMES) -> dict:
    player_rows = find_player_rows(stats, str(bet["player_name"]))
    current = current_stat(player_rows, str(bet["stat"]))
    team = latest_team(player_rows)
    completed = team_games_completed(stats, team)
    if completed == 0:
        completed = player_games_with_stats(player_rows)
    remaining = max(season_games - completed, 0)
    per_game = current / completed if completed else 0.0
    projected = per_game * season_games if completed else 0.0
    line = float(bet["line"])

    if str(bet["side"]) == "Over":
        amount_needed = max((line + 0.01) - current, 0.0)
        needed_pg = amount_needed / remaining if remaining else 0.0
    else:
        # For unders this is the maximum average the player can add while staying below the line.
        room = max((line - 0.01) - current, 0.0)
        needed_pg = room / remaining if remaining else 0.0

    status, icon = status_for_bet(str(bet["side"]), line, projected, completed)
    profit = american_profit(float(bet["stake"]), int(bet["odds"]))
    schedule_progress = completed / season_games if season_games else 0
    stat_progress = current / line if line > 0 else 0

    return {
        "player": bet["player_name"],
        "stat": bet["stat"],
        "side": bet["side"],
        "line": line,
        "current": current,
        "team": team or "—",
        "games_completed": completed,
        "games_remaining": remaining,
        "per_game": per_game,
        "projected": projected,
        "needed_per_game": needed_pg,
        "status": status,
        "status_icon": icon,
        "odds": int(bet["odds"]),
        "stake": float(bet["stake"]),
        "potential_profit": profit,
        "sportsbook": bet["sportsbook"],
        "notes": bet["notes"],
        "schedule_progress": schedule_progress,
        "stat_progress": stat_progress,
    }
