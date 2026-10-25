Static site (plain HTML/CSS/JS, no build, no external resources) with one tab per fantasy league and weekly flex-tiebreaker snapshots; works offline and on GitHub Pages (`.nojekyll` included).
Pages: `index.html` (tabbed home), one page per league (`best-league.html`, `zbt.html`, `oopsilons.html`, `spacex-ff.html`), and a shared `style.css`.
`zbt.html` is the latest ZBT weekly snapshot (Week 7); `best-league.html` is a template with placeholder tables and the correct league setup.
To add a new week: copy the current league page to `weeks/<league>-week<N>.html` (change the stylesheet and nav links to `../`) to archive it, then replace the data arrays in the league page.
Then add a link to the new week at the top of that league's Week list in `index.html` (newest first).
