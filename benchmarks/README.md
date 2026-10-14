# Benchmarks

Every number Dejo publishes comes from a script in this folder, and the raw results sit beside
it. Anyone can rerun them.

| script | what it measures | results |
|---|---|---|
| `benchmark_agents.py --journeys --runs 10` | three multi-step tasks, ten fresh Claude sessions each, against Playwright MCP and Chrome DevTools MCP. **The headline numbers.** | `benchmark-journeys10.json` |
| `benchmark_agents.py` | the same, on one-page lookups | `benchmark-agents.json` |
| `benchmark_agents.py --site <domain> --runs 10 --out <file>` | one site, ten fresh sessions per tool | `benchmark-repeat10-*.json`, `benchmark-fixed10-*.json` |
| `benchmark_tools.py` | the same steps through each MCP tool, driven by hand, counting calls and bytes | `benchmark-tools.json` |
| `benchmark_sites.py` | real public sites, learned once and then replayed from memory | `benchmark-sites.json` |
| `benchmark.py` | the demo site in `engine/tests/demo_site/`: learn, replay, a changed site, a second task | printed |

Run from the repo root, inside the project's virtualenv:

```bash
python benchmarks/benchmark_agents.py --journeys --runs 10
```

`benchmark_agents.py` needs the `claude` command signed in and Node for the two `npx`
servers it compares against.

**The results files were recorded while Dejo was still called Cairn**, so they say `cairn`
where they mean Dejo. They are kept exactly as recorded rather than edited.
