from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from tracker_logic import STAT_OPTIONS, evaluate_bet, normalize_bets, projection_history

SEASON = 2026
ROOT = Path(__file__).resolve().parent
BETS_PATH = ROOT / "bets.csv"
NFLVERSE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    f"stats_player/stats_player_week_{SEASON}.csv"
)

st.set_page_config(
    page_title="Season Long Bet Tracker",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 5rem; max-width: 760px;}
[data-testid="stMetric"] {background: rgba(128,128,128,.08); padding: .75rem; border-radius: 14px;}
.bet-card {border: 1px solid rgba(128,128,128,.23); border-radius: 18px; padding: 14px 16px; margin: 10px 0 14px;}
.bet-title {font-size: 1.08rem; font-weight: 750; margin-bottom: 2px;}
.bet-sub {opacity: .72; font-size: .88rem; margin-bottom: 10px;}
.status {font-weight: 700;}
.pace-badge {display:inline-block; font-size:.78rem; font-weight:800; padding:4px 9px; border-radius:999px; margin-top:5px;}
.pace-green {background:rgba(34,197,94,.15); color:#22c55e;}
.pace-yellow {background:rgba(234,179,8,.16); color:#d4a400;}
.pace-red {background:rgba(239,68,68,.15); color:#ef4444;}
.pace-gray {background:rgba(128,128,128,.14); color:inherit;}
.small {font-size: .85rem; opacity: .72;}
hr {margin: 1rem 0 !important;}
</style>
""",
    unsafe_allow_html=True,
)


def load_bets() -> pd.DataFrame:
    if not BETS_PATH.exists():
        return pd.DataFrame(columns=["player_name", "stat", "side", "line", "odds", "stake", "sportsbook", "notes"])
    return normalize_bets(pd.read_csv(BETS_PATH))


@st.cache_data(ttl=3600, show_spinner=False)
def load_stats() -> tuple[pd.DataFrame, str | None, datetime]:
    """Fetch the current weekly nflverse player file.

    A 404 is expected before the first weekly stats file of the season exists.
    """
    checked_at = datetime.now(ZoneInfo("America/New_York"))
    try:
        response = requests.get(NFLVERSE_URL, timeout=20)
        if response.status_code == 404:
            return pd.DataFrame(), "2026 weekly stats have not been published yet.", checked_at
        response.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        if "season_type" in df.columns:
            df = df[df["season_type"].astype(str).eq("REG")].copy()
        return df, None, checked_at
    except Exception as exc:
        return pd.DataFrame(), f"Could not refresh NFL stats right now: {exc}", checked_at


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def fmt_odds(odds: int) -> str:
    if odds == 0:
        return "Odds not entered"
    return f"+{odds}" if odds > 0 else str(odds)


st.title("Berk's Book Futures")
st.caption(f"2026 NFL season-long bet tracker • weekly stats via nflverse")

bets = load_bets()
stats, stats_error, stats_checked_at = load_stats()

left, right = st.columns([1.25, 1])
with left:
    if st.button("↻ Refresh stats", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with right:
    st.caption("Auto-checks at most once per hour")

refresh_label = stats_checked_at.strftime("%b %d • %I:%M %p ET").replace(" 0", " ")
if stats_error:
    st.info(f"{stats_error}\n\n**Last refresh attempt:** {refresh_label}")
elif not stats.empty:
    max_week = int(pd.to_numeric(stats.get("week"), errors="coerce").max()) if "week" in stats.columns else 0
    st.success(f"**Stats through Week {max_week}**  •  Last refreshed {refresh_label}")
else:
    st.info(f"No weekly stats are available yet.  •  Last checked {refresh_label}")

if bets.empty:
    st.warning("No bets are in bets.csv yet. Add your futures in the Manage Bets tab below.")
    evaluated = []
else:
    evaluated = [evaluate_bet(row, stats) for _, row in bets.iterrows()]

if evaluated:
    total_staked = sum(x["stake"] for x in evaluated)
    total_profit = sum(x["potential_profit"] for x in evaluated)
    on_pace = sum(x["status"] == "On pace" for x in evaluated)
    c1, c2, c3 = st.columns(3)
    c1.metric("Bets", len(evaluated))
    c2.metric("On pace", f"{on_pace}/{len(evaluated)}")
    if total_staked > 0:
        c3.metric("Risked", f"${total_staked:,.0f}", help=f"Potential profit: ${total_profit:,.2f}")
    else:
        c3.metric("Risked", "—", help="Add your stake and odds later if you want bankroll tracking.")

    st.subheader("My futures")
    status_order = {"On pace": 0, "Sweat": 1, "Off pace": 2, "Not started": 3}
    evaluated = sorted(evaluated, key=lambda x: (status_order.get(x["status"], 9), x["player"]))

    for item in evaluated:
        bet_label = f'{item["side"]} {fmt_num(item["line"])} {item["stat"]}'
        badge_class = {
            "On pace": "pace-green",
            "Sweat": "pace-yellow",
            "Off pace": "pace-red",
            "Not started": "pace-gray",
        }.get(item["status"], "pace-gray")
        st.markdown(
            f"""
<div class="bet-card">
  <div class="bet-title">{item['player']}</div>
  <div class="bet-sub">{bet_label} • {fmt_odds(item['odds'])}{(' • $' + format(item['stake'], ',.2f')) if item['stake'] > 0 else ''}{(' • ' + item['sportsbook']) if item['sportsbook'] else ''}</div>
  <span class="pace-badge {badge_class}">{item['status_icon']} {item['status']}</span>
</div>
""",
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Current", fmt_num(item["current"]))
        col2.metric("Projected final", fmt_num(item["projected"]) if item["games_completed"] else "—")
        col3.metric(
            "Need / game" if item["side"] == "Over" else "Max / game",
            fmt_num(item["needed_per_game"]) if item["games_remaining"] else "—",
        )

        if item["games_completed"]:
            # Use the actual whole-number cash target for the progress bar.
            progress_target = item["cash_target"] if item["side"] == "Over" else item["line"]
            raw_progress = min(max(item["current"] / progress_target if progress_target else 0, 0), 1)
            target_text = f"{fmt_num(item['current'])} / {fmt_num(item['cash_target'])} needed to cash" if item["side"] == "Over" else f"{fmt_num(item['current'])} / stay at {fmt_num(item['cash_target'])} or below"
            st.progress(raw_progress, text=f"{target_text} • {item['games_completed']} team games complete")

            # Weekly pace trend: projected season finish after every completed week.
            bet_row = bets.loc[bets["player_name"].eq(item["player"]) & bets["stat"].eq(item["stat"]) & bets["line"].eq(item["line"])].iloc[0]
            trend = projection_history(bet_row, stats)
            if not trend.empty:
                st.caption("Projected season finish by week")
                chart_df = trend.set_index("Week")[["Projected final", "Bet target"]]
                st.line_chart(chart_df, height=180, use_container_width=True)
                if len(trend) >= 2:
                    change = trend["Projected final"].iloc[-1] - trend["Projected final"].iloc[-2]
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    st.caption(f"{arrow} Projection moved {fmt_num(abs(change))} from last week")
        else:
            st.progress(0, text="Season has not started / stats not available yet")

        with st.expander("Details"):
            d1, d2 = st.columns(2)
            d1.write(f"**Team:** {item['team']}")
            d1.write(f"**Games remaining:** {item['games_remaining']}")
            d1.write(f"**Current per game:** {fmt_num(item['per_game'])}")
            d1.write(f"**Winning total:** {fmt_num(item['cash_target'])}{'+' if item['side'] == 'Over' else ' or fewer'}")
            if item["stake"] > 0 and item["odds"] != 0:
                d2.write(f"**Potential profit:** ${item['potential_profit']:,.2f}")
            else:
                d2.write("**Potential profit:** —")
            d2.write(f"**Sportsbook:** {item['sportsbook'] or '—'}")
            d2.write(f"**Notes:** {item['notes'] or '—'}")

st.divider()
manage, about = st.tabs(["Manage Bets", "How it works"])

with manage:
    st.caption("Edit this table, then download the updated bets.csv. For the first deployment, replace bets.csv in your GitHub repo with the downloaded file.")
    editor_base = bets.copy()
    if editor_base.empty:
        editor_base = pd.DataFrame([
            {"player_name": "", "stat": "Passing Yards", "side": "Over", "line": 0.0, "odds": -110, "stake": 20.0, "sportsbook": "DraftKings", "notes": ""}
        ])

    edited = st.data_editor(
        editor_base,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "stat": st.column_config.SelectboxColumn("Stat", options=list(STAT_OPTIONS.keys()), required=True),
            "side": st.column_config.SelectboxColumn("Side", options=["Over", "Under"], required=True),
            "line": st.column_config.NumberColumn("Line", min_value=0.0, step=0.5, required=True),
            "odds": st.column_config.NumberColumn("Odds", step=5, required=True),
            "stake": st.column_config.NumberColumn("Stake", min_value=0.0, step=5.0, format="$%.2f"),
        },
        key="bets_editor",
    )
    cleaned = normalize_bets(edited)
    csv_bytes = cleaned.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download updated bets.csv",
        data=csv_bytes,
        file_name="bets.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.caption("Why download? Streamlit Cloud's local filesystem is not guaranteed permanent. Keeping bets.csv in GitHub makes the data durable and free.")

with about:
    st.markdown(
        """
**Automatic stats:** the app checks nflverse's weekly player-stat release for the 2026 season. No paid API key is required.

**Pace:** it estimates a 17-game pace from completed team games, so a bye week does not automatically hurt the pace calculation.

**Need / game:** for an Over, this is the average needed over the remaining team games to clear the line. For an Under, it is the maximum average the player can add while staying below the line.

**Status:** green means the projected pace is comfortably on the correct side of the line, yellow means within roughly 5%, and red means currently off pace.

**Data note:** this is a personal tracking tool. Always verify settled sportsbook results against the book's official grading rules.
"""
    )

st.caption("Data: nflverse • Personal tracker")
