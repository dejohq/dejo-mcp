# Benchmarks

Every number Dejo publishes comes from a script in this folder, and the raw results sit beside
it. Anyone can rerun them.

| script | what it measures | results |
|---|---|---|
| `benchmark_agents.py --journeys --runs 10` | three multi-step tasks, ten fresh Claude sessions each, against Playwright MCP and Chrome DevTools MCP. **The headline numbers.** | `benchmark-journeys10.json` |
| `benchmark_agents.py` | the same, on one-page lookups | `benchmark-agents.json` |
| `benchmark_learning.py --runs 3 --tools dejo,playwright` | the FIRST run only: turns, tokens per turn, every tool result's size, whether a trail was really saved, whether the answer is right, and (Dejo) a second session that must answer in one call | `benchmark-learning-<date>.json` |
| `benchmark_agents.py --site <domain> --runs 10 --out <file>` | one site, ten fresh sessions per tool | `benchmark-repeat10-*.json`, `benchmark-fixed10-*.json` |
| `benchmark_tools.py` | the same steps through each MCP tool, driven by hand, counting calls and bytes | `benchmark-tools.json` |
| `benchmark_sites.py` | real public sites, learned once and then replayed from memory | `benchmark-sites.json` |
| `benchmark.py` | the demo site in `engine/tests/demo_site/`: learn, replay, a changed site, a second task | printed |
| `reliability.py` | 64 fixed step programs on real public sites. R01-R50 (iframes, shadow DOM, custom dropdowns, date pickers, hover menus, infinite scroll, tabs, suggestions, tables, long pages) are the score compared week on week; R51-R61 cover what other browser tools can do (dialogs, right clicks, tables and many fields as JSON, closing a tab, a page's own API answers, another language or a phone, cookies, PDFs), on practice sites and test services; R62-R64 cover a site that changes between visits (a dialog in the way of the next click, an element that arrives late, a menu item that moves). No model anywhere: it measures how well Dejo finds and uses elements. `--reference` runs the same steps through plain Playwright | `reliability-<date>.json` |

Run from the repo root, inside the project's virtualenv:

```bash
python benchmarks/benchmark_agents.py --journeys --runs 10
```

`reliability.py` runs on a schedule as it is: one command, exit code 0 whenever it finished,
the score in the JSON (`score.dejo.passed`) and one last line, "Dejo passed N of M". Each
failure carries its cause: element not found, wrong element, page not ready, site blocked or
captcha, answer changed on the site, or other.

`benchmark_agents.py` and `benchmark_learning.py` need the `claude` command signed in and Node
for the `npx` servers they compare against. `test_transcript.py` checks the turn-by-turn reader
against a real recorded run (`python -m pytest benchmarks`).

**Results recorded before 20 Oct 2026 ran Dejo in the developer's own browser profile.** The
script passed an empty `DEJO_PROFILE` meaning "clean", but Dejo reads an empty setting as unset.
So on github.com Dejo saw the signed-in page while Playwright MCP, started with `--isolated`, saw
the signed-out one. Every run since then gets its own empty profile.

**The results files were recorded while Dejo was still called Cairn**, so they say `cairn`
where they mean Dejo. They are kept exactly as recorded rather than edited.
