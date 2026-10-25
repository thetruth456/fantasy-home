Static fantasy home base (plain HTML/CSS/JS, no build, no external resources) at https://thetruth456.github.io/fantasy-home/ (repo thetruth456/fantasy-home); works offline and on GitHub Pages (`.nojekyll` included).
`index.html` is the tabbed home: each league tab shows that league's report immediately. Standalone pages: `best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`; shared `style.css`, `zbt-report.js`, favicon files.
`zbt.html` is the latest ZBT weekly snapshot (Week 7) and `best-league.html` is a template with the correct league setup; the same report markup is inlined in `index.html`.
To add a new week: copy the current league page to `weeks/<league>-week<N>.html` (use `../` for style, script and icon paths) to archive it, then update the report data (ZBT data lives in `zbt-report.js`).
Add the new week to the top of that league's snapshot list (the `weekline` paragraph) in the league page and in its `index.html` tab panel, newest first.
