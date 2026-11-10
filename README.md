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
| Kicker table: your K, then the best available unrostered K, up to 10 | Sleeper projections scored with that league's kicking settings, PrizePicks FG-made and kicking-points over/unders, FantasyPros `k` | `KICKERS` rows |
| Weather column on every player table | ESPN stadium and kickoff, Open-Meteo hourly forecast | `wx` on each row |
| Quick read, league setup, notes, "as of" line, titles | generated from the data above | `META` in each data file |

The pages hold no week-specific text: `report-core.js` fills the title, as-of line, quick read, setup, notes and week label from `window.REPORTS.<key>.META`, so a new week needs no HTML edit.

### Schedule and gate

The workflow cron is `0 * * * *` (every hour, UTC) plus manual `workflow_dispatch`. `tools/update.py` converts the time to `America/Los_Angeles` and decides:

* Saturday 1:00 PM PT through Sunday 10:59 AM PT: run (hourly).
* Any other time: run only in the 9 AM PT hour (once a day); otherwise exit without touching anything.
* `FORCE=true` (the workflow's `force` input, which the site button sets) skips the gate.

Because the gate uses local Pacific time, the Nov 1 DST change needs no edit. If nothing but timestamps would change, nothing is written and nothing is committed (unless forced).

### Failure handling

If one source fails, only that source keeps its previous values (for the same week) and the log says so (shown as warnings on the run page). If a source has no data for a new week yet, those cells show a dash instead of old numbers. If Sleeper itself is unreachable, nothing is changed and the run fails. One league failing does not stop the others from being committed. Nothing is ever fabricated. A failed weather fetch keeps the previous weather cells for the same week; a new week with no forecast shows a dash, `no forecast`, or `no obs` instead of last week's weather. Open-Meteo needs no API key. A failed PrizePicks fetch keeps the previous kicker lines for the same week.

### Defense table

Each league has a Defense table below the flex tiebreaker: your defenses (starter and bench), then the next 8 best unrostered DEF by Sleeper projection (`DEFENSE` in the data file, `<key>-t-def` in the page).

* Opp implied total = game total / 2 + this defense's own spread / 2 (spread is negative for the favorite). Game lines come from ESPN's public scoreboard (`site.api.espn.com`, DraftKings odds) through plain `urllib`.
* Prop-implied pts = Sleeper's projected DEF stat line scored with the league's settings, minus the points-allowed buckets, plus the expected points-allowed score for the opponent's implied total. The opponent's score is modelled as 14 scoring chances worth 7 (touchdown) or 3 (field goal), 77% of expected points from touchdowns, then scored with the league's own `pts_allow_*` settings. Yards-allowed buckets stay as Sleeper projects them.
* A game with no line yet, a game already played, or a bye shows dashes and falls back to the Sleeper projection (nothing is guessed). If ESPN is unreachable the previous lines for the same week are kept; the as-of line ends with "game lines as of ..." (or "game lines not available").

### Kicker table

Each league has a Kickers table below Defense: your kickers (starter, then bench), then the best available unrostered kickers until the table has 10 rows (`KICKERS` in the data file, `<key>-t-kick` on the page). If you roster more than 10 kickers, all of them are shown. If fewer than 10 kickers qualify, the table is shorter.

* Availability matches the waiver flex list: not rostered anywhere, has a team, the game is not complete, and the player is not Out, IR, PUP, Sus, NA, or Doubtful. Bye and already-played kickers are not added from waivers. Your own kickers stay on the table even on a bye or after they have played.
* Sleeper proj is the Sleeper stat line scored with this league's kicking settings (extra points, field-goal distance buckets, and miss penalties when the league has them). Sleeper publishes 50+ makes as one bucket. A league that pays a higher rate for 60+ is scored at its 50-59 rate for that bucket, because the 60+ share is not published. A played stat line that has only a total with no distance buckets cannot be re-scored; that final is not filled in by guessing.
* Fieldwork does not post kicker markets. FG made and Kicking pts are the PrizePicks two-way over/under (standard line). Alternate "demon" and "goblin" prices, and over-only prices, are not used. Kicking points are 3 per field goal and 1 per extra point. When both lines are posted, extra points are kicking points minus 3 times field goals, and the field-goal line is spread across Sleeper's distance mix, then scored with this league's settings. A single line scales that Sleeper shape so the posted stat matches. Miss penalties are not in the markets and are not deducted. If a line is missing, or the two lines cannot be field goals and extra points, or Sleeper has no distance mix for an uneven league, that cell is a dash.
* FP rank is the FantasyPros weekly kicker rank (`k.php`), colored inside this table only.

### Top keepers (Best League and Oopsilons only)

Best League and Oopsilons weekly reports have a Top keepers section after the waiver table and before league setup (`KEEPERS` in the data file, `<key>-t-keep` on the page). ZBT and SpaceX do not. It is the keep list for next season, from current rosters. The same `python tools/update.py` run fills it. The section stays inside the encrypted weekly report.

* Cost is this year's draft round minus 2, never earlier than the 1st or later than the 9th. A player with no pick in that draft costs a 9th. A trade does not change the round. The round is the round on this year's pick, including a keeper pick, so a second keep is another two rounds cheaper. Sleeper's `max_keepers` is a per-team cap and is not this rule. If a completed draft kept someone later than the 9th, the table still caps the cost at 9 and says so under the table.
* A player marked keeper in both of the previous two seasons is left off the ranking. The names are a footnote when the drafts say so. Nothing is hardcoded to one player.
* Value is expected points per game above replacement, minus the typical value of the middle pick in that keep round (the same ADP window as `tools/draftprior.py`). Expected points average this year's scoring, shrunk toward that player's Sleeper projection, and the Sleeper points of the same FantasyPros rest-of-season rank. Best League uses `ros-half-point-ppr-overall`; Oopsilons uses `ros-ppr-overall`. A missing input is a dash, and a player with no surplus is omitted rather than scored as zero. The table shows at most 24.

### Weather column

Every weekly-report player table (flex, defense, kickers, starters, bench, waivers) has a Weather column. It is the Open-Meteo model forecast for the kickoff hour, at the stadium on that week's ESPN schedule. It is not a station observation, including after the game has started. Neutral and international games use that stadium, not the home team's city. Both teams in a game share one forecast. Results are cached under `.cache/` for 45 minutes and requested in one batch per run.

* Outdoor: temperature °F, wind mph, conditions, plus precipitation chance when it is at least 30% and amount when it is at least 0.05 in.
* `(dome)` is a confirmed fixed roof (Allegiant, Caesars Superdome, Ford Field, U.S. Bank). No outdoor numbers are shown.
* `(roof ?)` is a retractable roof (AT&T, Lucas Oil, Mercedes-Benz, NRG, State Farm, and Santiago Bernabéu). The numbers are the outdoor forecast. The roof may be open or closed; that is not predicted.
* `(covered)` is SoFi's fixed canopy with open sides. Temperature and wind are outdoor. Precipitation may not reach the field.
* `(indoor ?)` is a building ESPN marks indoor that is not in the stadium table. No outdoor numbers.
* A neutral or non-US game also names the city (`Madrid`, `London`).
* `(final)` means the game has been played. `(kickoff)` means it is in progress. In both cases the numbers are still the Open-Meteo model value for the kickoff hour, not a measured observation. `Bye`, `no forecast` (past the model's 16-day horizon), `no obs` (that kickoff hour was missing from the model feed), and a dash were not filled in.
* ESPN's own indoor flag is not treated as a roof decision. It stays true for retractable roofs all season.

### Local run

```
python tools/update.py                    # honors the gate
FORCE=true python tools/update.py         # always runs
FORCE=true FH_OUT_DIR=/tmp/out python tools/update.py   # write elsewhere (testing)
FH_NOW=2026-10-25T17:00:00Z python tools/update.py      # pretend it is another time (test the gate)
```

Requires Python 3.9+ (`pip install -r tools/requirements.txt` gives zoneinfo data and `cryptography`). The weekly report also needs `FH_REPORT_PASSWORD` (the existing repository secret). There is no weather API key. The run needs HTTPS to Sleeper, Fieldwork, FantasyPros, ESPN, `api.open-meteo.com`, and `partner-api.prizepicks.com` (kicker over/unders). An unrecognized stadium may also call OpenStreetMap Nominatim once; a miss stays a dash. `.cache/` (Sleeper players dump, about 10 MB, refreshed daily, plus a short-lived weather cache) is git-ignored.

```
FH_REPORT_PASSWORD='…' FORCE=true python tools/update.py
FH_REPORT_PASSWORD='…' FORCE=true FH_OUT_DIR=/tmp/fh-out python tools/update.py
python tools/seal.py check
```

`check` confirms the password and that every `*-report.js` decrypts. The files are ciphertext. Do not commit a plaintext copy.

### Manual fixes

`tools/overrides.json` holds hand-entered fixes (for example a player Fieldwork lists under another name). Each entry is scoped to a `week` and ignored once the week rolls over, so stale fixes cannot leak into a new week.

## Buttons in the header

* **Refresh everything**: the single header button. It triggers the GitHub Actions update (rosters, Sleeper projections, props, FantasyPros ranks) and then reloads the data. Needs a one-time fine-grained token (stored only in the browser).
* **Refresh everything**: asks GitHub to run the update workflow now (`force=true`), waits for it to finish, reloads the four data files and redraws without reloading the page.
  * First click shows a one-time setup: create a fine-grained personal access token at https://github.com/settings/personal-access-tokens/new with Repository access: only `fantasy-home`, and Repository permissions: Actions: Read and write. Paste it into the panel.
  * The token is stored only in this browser's localStorage under `fh_gh_token`. It is never in the repo. "Forget GitHub token" removes it.
  * The new data is read through the GitHub contents API, so the page shows it right away; the public site itself updates once GitHub Pages redeploys (usually within a minute or two of the commit).
  * A wrong or expired token (401), a token without Actions access (403), a rate limit, a missing workflow (404) and a failed run each show a short message.

## Power Rankings and luck report (all leagues)

Every league (each tab of `index.html`, and the standalone `best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`) has three sub-tabs, in this order: **Power Rankings** (the default), **Luck report** and **Weekly report**. Power Rankings and the luck report are open to everyone; only the Weekly report asks for the password (see below), and only when it is clicked. Links on the home page: `#<league>` (Power Rankings), `#<league>-luck`, `#<league>-report`, with league = `best`, `zbt`, `oops` or `spacex`; older links `#<league>-power` and `#<league>-podcast` (luck) still work. Standalone pages use `#power`, `#luck` (or `#podcast`) and `#report`; no hash opens Power Rankings.

Both views are static snapshots. `python tools/podcast.py --league KEY [last_week]` writes `<key>-podcast-data.js` (Sleeper data only, rendered by `podcast.js`) and `python tools/power.py --league KEY [sims]` writes `<key>-power-data.js` (rendered by `power.js`); `--league all` does every league in `tools/leagues.py` (default `best`). The update workflow only commits `*-report.js`, and Refresh everything only reloads those files, so neither touches these views; re-run the two tools by hand to refresh them. Both tools count a week as completed once every NFL game of that week is final in Sleeper's scores feed, even before the league's `last_scored_leg` moves (usually the next morning). Injury misses are charged to the team holding the player that week; long-term return timelines live in `LONG_TERM` in `tools/podcast.py` (with source links) and need a manual check before each re-run. The W8* (current week) point uses the live week: Sleeper's `matchups/<week>` points for starters whose game is over (final) or under way (points so far, plus the rest of their value scaled by the game time left from Sleeper's scores feed), and simulates only players still to play; the current week comes from `last_scored_leg` + 1, checked against `/state/nfl`. The odds charts show each team's record next to its line label and in the legend (`(W-L)`, or `W-L-T` with ties), from completed weeks only (`last`, Sleeper's last scored week; the caption says which week); hover shows the record after each week. These come from the `recs` field (`{roster_id: [[W,L,T] after week 1, ...]}`) that `tools/power.py` writes; `python tools/records.py [--league KEY|all]` appends just that field to an existing power data file without re-running the simulation.

**Best League model frozen.** The user asked not to change the Best League model until they say so. `FROZEN` in `tools/leagues.py` keeps Best on the settings its live files were made with: TAU0 4.6 (instead of the 5.5 from `tools/power_cal.json`) and the injury list as checked Oct 31 (`LONG_TERM_OCT31` in `tools/podcast.py`, no `ACTIVATED` overrides). Both Best files were re-run after week 8 (Nov 2, night) with these frozen settings (fresh Sleeper inputs only). Remove the `best` entry from `FROZEN` to put Best on the current list and calibration.

How the power model works: each current-roster player is valued at his own season points per game, weighted gp/(gp+7), plus his Sleeper projection that week for the rest (zero on byes, this week's Out/IR tags and `LONG_TERM` absences from `tools/podcast.py`); a team's weekly mean is its best legal lineup. It simulates the rest of the regular season and Sleeper's fixed playoff bracket (10,000 runs by default, fixed seed), plus a random-opponent run for the schedule effect. Each run also draws a persistent team-strength offset with sd 1/sqrt(1/TAU0^2 + weeks/22.9^2); `FH_POWER_TAU0` overrides the preseason size (TAU0 in `tools/power_cal.json`; 4.6 reproduces the pre-update14 numbers). Future injuries are simulated (`tools/injury.py`): per-game absence rates by position and how many games an absence lasts, measured from Sleeper game logs 2021–25 (`python tools/injury.py` reproduces them). Each team gets 2,000 injury paths (`FH_POWER_PATHS`). When starters are out, the best lineup re-forms from the bench plus waiver fill-ins (the 3rd/4th-best unrostered player at each position). Team means are the injury-path averages, and each simulated season follows one path. Weekly noise drops to sqrt(sd^2 - injury week-to-week variance) so the total spread still matches real scores. Team edges over the league mean are scaled by beta_t = 1 - (1 - 0.51)*7.6/(7.6 + t) after week t (0.51 preseason). The preseason prior (`tools/draftprior.py`) is the injury-averaged best lineup of drafted players at Sleeper preseason projections. The "Pre-draft" point uses only keeper surplus x 0.95 (keeper value over replacement minus that of players with ADP near his pick), with extra uncertainty for the draft and the unknown rosters' injuries. Constants come from `tools/power_cal.json`, written by `python tools/power_calibrate.py --write`: a league with at least 36 past team-seasons (only Best League, 2022–25) uses its own fit; the others use the fit pooled over all leagues' history (Best League keeps TAU0 4.6 while frozen, see above).

## Password lock (encrypted data)

Only the weekly reports (rosters, lineups, waivers) are behind a password. The weekly report data files (`*-report.js`) hold only ciphertext; `lock.js` shows a password prompt inside the Weekly report view and decrypts in the browser (WebCrypto). Power Rankings and the luck report stay open to everyone in every league: the `*-podcast-data.js` and `*-power-data.js` files are plaintext on purpose, pages open on Power Rankings with no prompt, and the prompt appears only in the Weekly report sub-tab. Refresh everything and the token panel only appear after unlocking.

* Crypto (`tools/seal.py`): password -> PBKDF2-SHA256 (600,000 iterations, public salt in `tools/lock.json`) -> master key; each file and each write gets a fresh random salt (HKDF-SHA256 -> AES-256-GCM key) and a fresh random IV. `tools/lock.json` also holds an encrypted check value, so a wrong password fails the build instead of writing files nobody can open.
* The password is read from env `FH_REPORT_PASSWORD` (the Action uses the repository secret of the same name). Without it, `tools/update.py` exits with an error and writes nothing (`tools/podcast.py` and `tools/power.py` don't need it). The workflow also runs `python tools/seal.py verify` before committing.
* "Remember on this device" stores the derived master key (not the password) in localStorage; the **Lock** link in the header forgets it.
* Change the password: `FH_REPORT_PASSWORD_OLD=<old> FH_REPORT_PASSWORD=<new> python tools/seal.py init`, commit `tools/lock.json` and the `*-report.js` files, and update the secret.
* `python tools/seal.py check` confirms the password and that every report data file decrypts. Needs `pip install cryptography`.
* Git history from before the lock still has plaintext data files.

## Pages and files

* `index.html`: tabbed home, one tab per league. Standalone pages: `best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`.
* `style.css`, `lock.js` (password gate and decryption), `report-core.js` (renders the tables and text), `refresh.js` (Refresh everything).
* `podcast.js` (sub-tabs, luck report), `power.js` (Power Rankings and odds charts); data: `<key>-podcast-data.js`, `<key>-power-data.js` (plaintext snapshots from `tools/podcast.py` / `tools/power.py`).
* `*-report.js`: generated data files. Do not edit by hand; changes are overwritten by the next run.
* `tools/`: `update.py` (orchestration and gate), `sources.py` (Sleeper, Fieldwork, FantasyPros, ESPN fetchers), `build.py` (scoring, props, ranks, waiver list, text), `keepers.py` (Best League and Oopsilons top-keeper table), `overrides.json`.
* `.github/workflows/update.yml`: the schedule.

## Week roll-over

Nothing to do by hand. Sleeper switches `week` on its own (around Tuesday). Until Fieldwork and FantasyPros publish the new week, the props and FP cells show dashes (the log says so); the next hourly or daily run fills them in. To keep a copy of an old week, copy the league page to `weeks/<league>-week<N>.html` before it rolls (optional).

## Setup checklist (once)

1. Push this repo to `main` (a token with the `workflow` scope, or a Workflows permission for fine-grained tokens, is needed to push `.github/workflows/`).
2. Settings, Actions, General: Workflow permissions: Read and write (the workflow also declares `contents: write`).
3. Run the "Update fantasy data" workflow once from the Actions tab to confirm the runner can reach Sleeper, Fieldwork, FantasyPros, ESPN, and Open-Meteo (the log shows "ESPN game lines: N teams" and "weather: N teams"; N for lines should be about 2 per game).
