# Berk's Book Futures Tracker

A free, mobile-friendly Streamlit dashboard for tracking 2026 NFL season-long player props.

## What it does

- Pulls weekly NFL player statistics from the free nflverse data release.
- Tracks season-long Overs and Unders.
- Shows current total, 17-game pace, games remaining, and the average needed per remaining game.
- Accounts for bye weeks by estimating completed games from team weekly-stat rows.
- Calculates stake and potential profit from American odds.
- Works well from an iPhone browser and can be added to the Home Screen.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Put in your real bets

Edit `bets.csv`. Supported stat names are:

- Passing Yards
- Rushing Yards
- Receiving Yards
- Pass + Rush Yards
- Rush + Receiving Yards
- Receptions
- Passing TDs
- Rushing TDs
- Receiving TDs
- Rush + Receiving TDs
- Interceptions Thrown
- Completions
- Pass Attempts
- Carries
- Targets

The app also has a **Manage Bets** tab. Because Streamlit Community Cloud does not promise durable writes to the app's local filesystem, the tab lets you download a refreshed `bets.csv`; replace the repo copy with that file.

## Free deployment on Streamlit Community Cloud

1. Create a GitHub repository, for example `berks-book-futures`.
2. Upload all files from this folder, including `.streamlit/config.toml`.
3. Sign into Streamlit Community Cloud and connect GitHub.
4. Choose **Create app** and select your repository.
5. Set the entrypoint to `app.py` and deploy.
6. Open the resulting `streamlit.app` URL on your phone.
7. On iPhone, use Safari **Share → Add to Home Screen** for app-like access.

## Weekly updates

There is no scheduler to maintain. Every time the app loads, it checks the current nflverse weekly file, and Streamlit caches the result for one hour. Use **Refresh stats** to force a new check.

For 2026, the weekly file URL is:

`https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv`

Before the first 2026 regular-season weekly file exists, the dashboard will simply show the bets as **Not started**.

## Notes

- nflverse is a community-maintained data source, not a sportsbook grading source.
- If a player's displayed name differs from the name in nflverse, update `player_name` in `bets.csv` to match.
- A future version can persist additions directly from the phone using a small free database or GitHub write integration.


## Odds and stakes
The five starting bets are loaded with the exact player/stat/side/line you provided. Odds and stake are left unset until you provide them, so the app does not guess bankroll information.
