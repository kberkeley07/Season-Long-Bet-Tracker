from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    page_title="Berk's Book Futures",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 5rem; max-width: 760px;}
[data-testid="stMetric"] {background: rgba(128,128,128,.08); padding: .78rem; border-radius: 14px;}
.bet-card {border: 1px solid rgba(128,128,128,.23); border-radius: 18px; padding: 14px 16px; margin: 14px 0 10px;}
.bet-title {font-size: 1.1rem; font-weight: 760; margin-bottom: 2px;}
.bet-sub {opacity: .72; font-size: .88rem; margin-bottom: 8px;}
.pace-badge {display:inline-block; font-size:.78rem; font-weight:800; padding:4px 9px; border-radius:999px;}
.pace-green {background:rgba(34,197,94,.15); color:#22c55e;}
.pace-yellow {background:rgba(234,179,8,.16); color:#d4a400;}
.pace-red {background:rgba(239,68,68,.15); color:#ef4444;}
.pace-gray {background:rgba(128,128,128,.14); color:inherit;}
.money-win {color:#22c55e; font-weight:700;}
.money-loss {color:#ef4444; font-weight:700;}
.money-neutral {opacity:.72; font-weight:650;}
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
    """Fetch the current weekly nflverse player file."""
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
    value = float(value or 0)
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def fmt_odds(odds: int) -> str:
    if odds == 0:
        return "Odds not entered"
    return f"+{odds}" if odds > 0 else str(odds)


def fmt_signed_money(value: float) -> str:
    if value > 0:
        return f"+${value:,.2f}"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return "$0.00"


def render_projection_chart(trend: pd.DataFrame) -> None:
    """Render a clean pace chart without Streamlit's auto-generated aggregation labels."""
    if len(trend) < 2:
        st.caption("Trend chart starts after Week 2 so there is actually a trend to compare.")
        return

    chart_data = trend[["Week", "Projected final", "Bet target"]].copy()
    chart_data["Week"] = chart_data["Week"].astype(int)
    spec = {
        "height": 185,
        "layer": [
            {
                "mark": {"type": "line", "point": True, "strokeWidth": 3},
                "encoding": {
                    "x": {
                        "field": "Week",
                        "type": "ordinal",
                        "title": "Week",
                        "axis": {"labelAngle": 0},
                    },
                    "y": {
                        "field": "Projected final",
                        "type": "quantitative",
                        "title": "Projected final",
                        "scale": {"zero": False},
                    },
                    "tooltip": [
                        {"field": "Week", "type": "ordinal", "title": "Week"},
                        {"field": "Projected final", "type": "quantitative", "title": "Projected", "format": ",.1f"},
                    ],
                },
            },
            {
                "mark": {"type": "rule", "strokeDash": [6, 5], "opacity": 0.7},
                "encoding": {
                    "y": {
                        "field": "Bet target",
                        "type": "quantitative",
                        "title": "Projected final",
                    }
                },
            },
        ],
        "config": {"view": {"stroke": None}},
    }
    st.vega_lite_chart(chart_data, spec, use_container_width=True)


st.title("Berk's Book Futures")
st.caption(f"{SEASON} NFL season-long bet tracker • weekly stats via nflverse")

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
    evaluated: list[dict] = []
else:
    evaluated = [evaluate_bet(row, stats) for _, row in bets.iterrows()]

    # Backward compatibility during Streamlit redeploys if app.py updates a moment
    # before tracker_logic.py.
    for item in evaluated:
        stake = float(item.get("stake", 0) or 0)
        profit = float(item.get("potential_profit", 0) or 0)
        payout = float(item.get("potential_payout", stake + profit if stake > 0 else 0.0) or 0)
        projected_win = item.get("projected_win")
        if projected_win is None and item.get("games_completed", 0) > 0:
            if item.get("side") == "Over":
                projected_win = float(item.get("projected", 0)) > float(item.get("line", 0))
            else:
                projected_win = float(item.get("projected", 0)) < float(item.get("line", 0))
        item.setdefault("potential_payout", payout)
        item.setdefault("win_net", profit)
        item.setdefault("loss_net", -stake if stake > 0 else 0.0)
        item.setdefault("projected_win", projected_win)
        item.setdefault("pace_net", profit if projected_win is True else (-stake if projected_win is False else 0.0))
        item.setdefault("pace_return", payout if projected_win is True else 0.0)

if evaluated:
    total_staked = sum(float(x.get("stake", 0) or 0) for x in evaluated)
    total_profit = sum(float(x.get("potential_profit", 0) or 0) for x in evaluated)
    total_payout = sum(float(x.get("potential_payout", 0) or 0) for x in evaluated)

    started = [x for x in evaluated if x.get("projected_win") is not None]
    projected_wins = sum(x.get("projected_win") is True for x in started)
    projected_losses = sum(x.get("projected_win") is False for x in started)
    pace_net = sum(float(x.get("pace_net", 0) or 0) for x in started)
    pace_return = sum(float(x.get("pace_return", 0) or 0) for x in started)

    st.subheader("Current money outlook")
    m1, m2 = st.columns(2)
    m1.metric("Total risked", f"${total_staked:,.2f}")
    if started:
        m2.metric(
            "If current pace holds",
            fmt_signed_money(pace_net),
            help="Projected net profit/loss if every current season pace finished on the same side of its line.",
        )
    else:
        m2.metric("If current pace holds", "—")

    m3, m4 = st.columns(2)
    m3.metric(
        "Projected cash returned",
        f"${pace_return:,.2f}" if started else "—",
        help="Gross payout returned by bets currently projected to win. Losing wagers return $0.",
    )
    m4.metric(
        "Projected record",
        f"{projected_wins}–{projected_losses}" if started else "—",
        help="Based strictly on each bet's projected final total versus its line.",
    )
    st.caption("Pace-based money is a projection, not a settled result. Yellow 'Sweat' bets still count according to which side of the line their current projection is on.")

    if started:
        with st.expander("Pace-based payout breakdown"):
            payout_rows = []
            for x in evaluated:
                if x.get("projected_win") is None:
                    result_label = "No pace yet"
                elif x.get("projected_win") is True:
                    result_label = "Projected win"
                else:
                    result_label = "Projected loss"
                payout_rows.append({
                    "Player": x.get("player", ""),
                    "Pace result": result_label,
                    "Status": x.get("status", ""),
                    "Projected net P/L": float(x.get("pace_net", 0) or 0),
                    "Cash returned": float(x.get("pace_return", 0) or 0),
                })
            payout_df = pd.DataFrame(payout_rows)
            st.dataframe(
                payout_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Projected net P/L": st.column_config.NumberColumn(format="$%.2f"),
                    "Cash returned": st.column_config.NumberColumn(format="$%.2f"),
                },
            )

    with st.expander("Best / worst case"):
        e1, e2 = st.columns(2)
        e1.metric("All-win net profit", f"+${total_profit:,.2f}")
        e2.metric("All-win gross payout", f"${total_payout:,.2f}")
        e3, e4 = st.columns(2)
        e3.metric("All-lose net P/L", f"-${total_staked:,.2f}")
        all_win_roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
        e4.metric("All-win ROI", f"{all_win_roi:.1f}%")

    st.subheader("My futures")
    status_order = {"On pace": 0, "Sweat": 1, "Off pace": 2, "Not started": 3}
    evaluated = sorted(evaluated, key=lambda x: (status_order.get(x.get("status"), 9), x.get("player", "")))

    for item in evaluated:
        bet_label = f'{item["side"]} {fmt_num(item["line"])} {item["stat"]}'
        badge_class = {
            "On pace": "pace-green",
            "Sweat": "pace-yellow",
            "Off pace": "pace-red",
            "Not started": "pace-gray",
        }.get(item.get("status"), "pace-gray")

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
        col2.metric("Projected", fmt_num(item["projected"]) if item["games_completed"] else "—")
        col3.metric(
            "Need / game" if item["side"] == "Over" else "Max / game",
            fmt_num(item["needed_per_game"]) if item["games_remaining"] else "—",
        )

        if item["stake"] > 0 and item["odds"] != 0:
            if item.get("projected_win") is True:
                st.markdown(
                    f'<div class="money-win">If current pace holds: +${item["pace_net"]:,.2f} net • ${item["pace_return"]:,.2f} returned</div>',
                    unsafe_allow_html=True,
                )
            elif item.get("projected_win") is False:
                st.markdown(
                    f'<div class="money-loss">If current pace holds: -${item["stake"]:,.2f} net • $0 returned</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<div class="money-neutral">No pace-based payout projection yet.</div>', unsafe_allow_html=True)

        if item["games_completed"]:
            progress_target = item["cash_target"] if item["side"] == "Over" else item["line"]
            raw_progress = min(max(item["current"] / progress_target if progress_target else 0, 0), 1)
            if item["side"] == "Over":
                progress_text = f"{fmt_num(item['current'])} of {fmt_num(item['cash_target'])} target • {item['games_completed']} of 17 team games"
            else:
                progress_text = f"{fmt_num(item['current'])} current • target {fmt_num(item['cash_target'])} or fewer • {item['games_completed']} of 17 team games"
            st.progress(raw_progress, text=progress_text)

            bet_matches = bets.loc[
                bets["player_name"].eq(item["player"])
                & bets["stat"].eq(item["stat"])
                & bets["line"].eq(item["line"])
            ]
            if not bet_matches.empty:
                trend = projection_history(bet_matches.iloc[0], stats)
                st.caption("Weekly pace trend")
                render_projection_chart(trend)
                if len(trend) >= 2:
                    change = trend["Projected final"].iloc[-1] - trend["Projected final"].iloc[-2]
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    st.caption(f"{arrow} Projection moved {fmt_num(abs(change))} from last week • dashed line = bet target")
        else:
            st.progress(0, text="No completed-game pace available yet")

        with st.expander("Details"):
            d1, d2 = st.columns(2)
            d1.write(f"**Team:** {item['team']}")
            d1.write(f"**Games remaining:** {item['games_remaining']}")
            d1.write(f"**Current per game:** {fmt_num(item['per_game'])}")
            d1.write(f"**Winning total:** {fmt_num(item['cash_target'])}{'+' if item['side'] == 'Over' else ' or fewer'}")
            if item["stake"] > 0 and item["odds"] != 0:
                d2.write(f"**Wager:** ${item['stake']:,.2f} at {fmt_odds(item['odds'])}")
                d2.write(f"**If bet wins:** +${item['win_net']:,.2f} net")
                d2.write(f"**Total payout if won:** ${item['potential_payout']:,.2f}")
                d2.write(f"**If bet loses:** -${item['stake']:,.2f} net")
            else:
                d2.write("**Wager / payout:** —")
            d2.write(f"**Sportsbook:** {item['sportsbook'] or '—'}")
            d2.write(f"**Notes:** {item['notes'] or '—'}")

st.divider()
manage, about = st.tabs(["Manage Bets", "How it works"])

with manage:
    st.caption("Edit the table, download the updated bets.csv, then replace bets.csv in GitHub. This keeps your data durable on free Streamlit hosting.")
    editor_base = bets.copy()
    if editor_base.empty:
        editor_base = pd.DataFrame([
            {
                "player_name": "",
                "stat": "Passing Yards",
                "side": "Over",
                "line": 0.0,
                "odds": -110,
                "stake": 20.0,
                "sportsbook": "DraftKings",
                "notes": "",
            }
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

with about:
    st.markdown(
        """
**Automatic stats:** the app checks nflverse's weekly player-stat release for the 2026 season. No paid API key is required.

**Projected:** current per-team-game pace extended across a 17-game regular season. Bye weeks do not automatically hurt the projection.

**Need / game:** for an Over, the average needed over remaining team games to clear the line. For an Under, the maximum average the player can add while staying below the line.

**Status:** green is comfortably on pace, yellow is within roughly 5% of the line, and red is currently off pace.

**If current pace holds:** the money projection treats a bet as a projected win when its projected final total is on the winning side of the line, and as a projected loss otherwise. This is not a settled result.

**Payout language:** net profit excludes the returned stake. Cash returned / gross payout includes the original stake plus profit.

**Data note:** always verify settled sportsbook results against the book's official grading rules.
"""
    )

st.caption("Data: nflverse • Personal tracker")
