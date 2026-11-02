# Fantasy home base

Static site (plain HTML/CSS/JS, no build step, no external resources) at https://thetruth456.github.io/fantasy-home/ (repo `thetruth456/fantasy-home`). `.nojekyll` is included for GitHub Pages.

## How the data stays current

A GitHub Action (`.github/workflows/update.yml`) runs `python tools/update.py` on a GitHub-hosted runner, rewrites the four `*-report.js` data files and commits them to `main` only when something changed. Public-repo runners are free, so this costs nothing.

| What | Source | Where it ends up |
| --- | --- | --- |
| Current week, rosters, lineups, opponents, game state | Sleeper API | `STARTERS`, `BENCH` rows |
| Sleeper projections, re-scored to each league's settings | Sleeper API | `proj` / `pn` |
| Waiver list (about 10, at least 2 WR and 2 RB, at most 14) | Sleeper free agents ranked by prop-implied pts | `WAIVER` rows |
| Props and prop-implied pts (0.1/yd rush and rec, 1/reception, 6 x anytime-TD probability) | Fieldwork | `pp` and the line columns |
| FP rank (flex rank for RB/WR/TE, position rank for QB/K/DEF) | FantasyPros consensus | `fp` |
| Game total and spread (Defense table) | ESPN scoreboard API (DraftKings lines) | `total`, `spread`, `opptot` on `DEFENSE` rows |
| Defense table: your DEF, then the next 8 best unrostered DEF by Sleeper projection | Sleeper, FantasyPros `dst`, ESPN | `DEFENSE` rows |
| Quick read, league setup, notes, "as of" line, titles | generated from the data above | `META` in each data file |

The pages hold no week-specific text: `report-core.js` fills the title, as-of line, quick read, setup, notes and week label from `window.REPORTS.<key>.META`, so a new week needs no HTML edit.

### Schedule and gate

The workflow cron is `0 * * * *` (every hour, UTC) plus manual `workflow_dispatch`. `tools/update.py` converts the time to `America/Los_Angeles` and decides:

* Saturday 1:00 PM PT through Sunday 10:59 AM PT: run (hourly).
* Any other time: run only in the 9 AM PT hour (once a day); otherwise exit without touching anything.
* `FORCE=true` (the workflow's `force` input, which the site button sets) skips the gate.

Because the gate uses local Pacific time, the Nov 1 DST change needs no edit. If nothing but timestamps would change, nothing is written and nothing is committed (unless forced).

### Failure handling

If one source fails, only that source keeps its previous values (for the same week) and the log says so (shown as warnings on the run page). If a source has no data for a new week yet, those cells show a dash instead of old numbers. If Sleeper itself is unreachable, nothing is changed and the run fails. One league failing does not stop the others from being committed. Nothing is ever fabricated.

### Defense table

Each league has a Defense table below the flex tiebreaker: your defenses (starter and bench), then the next 8 best unrostered DEF by Sleeper projection (`DEFENSE` in the data file, `<key>-t-def` in the page).

* Opp implied total = game total / 2 + this defense's own spread / 2 (spread is negative for the favorite). Game lines come from ESPN's public scoreboard (`site.api.espn.com`, DraftKings odds) through plain `urllib`.
* Prop-implied pts = Sleeper's projected DEF stat line scored with the league's settings, minus the points-allowed buckets, plus the expected points-allowed score for the opponent's implied total. The opponent's score is modelled as 14 scoring chances worth 7 (touchdown) or 3 (field goal), 77% of expected points from touchdowns, then scored with the league's own `pts_allow_*` settings. Yards-allowed buckets stay as Sleeper projects them.
* A game with no line yet, a game already played, or a bye shows dashes and falls back to the Sleeper projection (nothing is guessed). If ESPN is unreachable the previous lines for the same week are kept; the as-of line ends with "game lines as of ..." (or "game lines not available").

### Local run

```
python tools/update.py                    # honors the gate
FORCE=true python tools/update.py         # always runs
FORCE=true FH_OUT_DIR=/tmp/out python tools/update.py   # write elsewhere (testing)
FH_NOW=2026-10-25T17:00:00Z python tools/update.py      # pretend it is another time (test the gate)
```

Requires Python 3.9+ (`pip install -r tools/requirements.txt` gives zoneinfo data on machines without it). `.cache/` (Sleeper players dump, about 10 MB, refreshed daily) is git-ignored.

### Manual fixes

`tools/overrides.json` holds hand-entered fixes (for example a player Fieldwork lists under another name). Each entry is scoped to a `week` and ignored once the week rolls over, so stale fixes cannot leak into a new week.

## Buttons in the header

* **Refresh everything**: the single header button. It triggers the GitHub Actions update (rosters, Sleeper projections, props, FantasyPros ranks) and then reloads the data. Needs a one-time fine-grained token (stored only in the browser).
* **Refresh everything**: asks GitHub to run the update workflow now (`force=true`), waits for it to finish, reloads the four data files and redraws without reloading the page.
  * First click shows a one-time setup: create a fine-grained personal access token at https://github.com/settings/personal-access-tokens/new with Repository access: only `fantasy-home`, and Repository permissions: Actions: Read and write. Paste it into the panel.
  * The token is stored only in this browser's localStorage under `fh_gh_token`. It is never in the repo. "Forget GitHub token" removes it.
  * The new data is read through the GitHub contents API, so the page shows it right away; the public site itself updates once GitHub Pages redeploys (usually within a minute or two of the commit).
  * A wrong or expired token (401), a token without Actions access (403), a rate limit, a missing workflow (404) and a failed run each show a short message.

## Best League podcast view

`index.html` (Best League tab) and `best-league.html` have three sub-tabs: **Weekly report** (default), **Podcast: luck report** (`#best-podcast` on the home page, `#podcast` on the standalone page) and **Podcast: Power Rankings** (`#best-power` / `#power`). The podcast view is a static snapshot: `best-podcast-data.js` is written once by `python tools/podcast.py [last_week]` (Sleeper data only) and rendered by `podcast.js`. The update workflow only commits `*-report.js`, and Refresh everything only reloads those files, so neither touches the podcast view. Re-run `tools/podcast.py` by hand to refresh it. Injury misses are charged to the team holding the player that week; long-term return timelines live in `LONG_TERM` in `tools/podcast.py` (with source links) and need a manual check before each re-run.

Power rankings work the same way: `python tools/power.py [sims]` writes `best-power-data.js` (rendered by `power.js`). Each current-roster player is valued at his own season points per game, weighted gp/(gp+7), plus his Sleeper projection that week for the rest (zero on byes, this week's Out/IR tags and `LONG_TERM` absences from `tools/podcast.py`); a team's weekly mean is its best legal lineup. It simulates the rest of the regular season and Sleeper's fixed playoff bracket (10,000 runs by default, fixed seed), plus a random-opponent run for the schedule effect. Each run also draws a persistent team-strength offset with sd 1/sqrt(1/TAU0^2 + weeks/22.9^2); `FH_POWER_TAU0` (default 6.8 pts/wk, calibrated from this season's preseason-projection error) sets the preseason size.

## Pages and files

* `index.html`: tabbed home, one tab per league. Standalone pages: `best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`.
* `style.css`, `report-core.js` (renders the tables and text), `refresh.js` (both buttons).
* `*-report.js`: generated data files. Do not edit by hand; changes are overwritten by the next run.
* `tools/`: `update.py` (orchestration and gate), `sources.py` (Sleeper, Fieldwork, FantasyPros, ESPN fetchers), `build.py` (scoring, props, ranks, waiver list, text), `overrides.json`.
* `.github/workflows/update.yml`: the schedule.

## Week roll-over

Nothing to do by hand. Sleeper switches `week` on its own (around Tuesday). Until Fieldwork and FantasyPros publish the new week, the props and FP cells show dashes (the log says so); the next hourly or daily run fills them in. To keep a copy of an old week, copy the league page to `weeks/<league>-week<N>.html` before it rolls (optional).

## Setup checklist (once)

1. Push this repo to `main` (a token with the `workflow` scope, or a Workflows permission for fine-grained tokens, is needed to push `.github/workflows/`).
2. Settings, Actions, General: Workflow permissions: Read and write (the workflow also declares `contents: write`).
3. Run the "Update fantasy data" workflow once from the Actions tab to confirm the runner can reach Sleeper, Fieldwork, FantasyPros and ESPN (the log shows "ESPN game lines: N teams"; N should be about 2 per game).
