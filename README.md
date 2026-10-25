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

## Pages and files

* `index.html`: tabbed home, one tab per league. Standalone pages: `best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`.
* `style.css`, `report-core.js` (renders the tables and text), `refresh.js` (both buttons).
* `*-report.js`: generated data files. Do not edit by hand; changes are overwritten by the next run.
* `tools/`: `update.py` (orchestration and gate), `sources.py` (Sleeper, Fieldwork, FantasyPros fetchers), `build.py` (scoring, props, ranks, waiver list, text), `overrides.json`.
* `.github/workflows/update.yml`: the schedule.

## Week roll-over

Nothing to do by hand. Sleeper switches `week` on its own (around Tuesday). Until Fieldwork and FantasyPros publish the new week, the props and FP cells show dashes (the log says so); the next hourly or daily run fills them in. To keep a copy of an old week, copy the league page to `weeks/<league>-week<N>.html` before it rolls (optional).

## Setup checklist (once)

1. Push this repo to `main` (a token with the `workflow` scope, or a Workflows permission for fine-grained tokens, is needed to push `.github/workflows/`).
2. Settings, Actions, General: Workflow permissions: Read and write (the workflow also declares `contents: write`).
3. Run the "Update fantasy data" workflow once from the Actions tab to confirm the runner can reach Sleeper, Fieldwork and FantasyPros.
