"""Draw the README chart from the raw benchmark results, so the picture can never drift from them.

    python benchmarks/make_chart.py

Reads `benchmark-journeys10.json` and writes two SVGs into `.github/assets/`, one for light
mode and one for dark, which the README shows through a <picture> element. Each point is the
tool calls of one fresh session, summed over the three tasks. The results were recorded
while Dejo was called Cairn, so the file names Dejo `cairn`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "benchmarks" / "benchmark-journeys10.json"
OUT = ROOT / ".github" / "assets"

RUNS = 10
WIDTH, HEIGHT = 880, 380
LEFT, RIGHT, TOP, BOTTOM = 56, 246, 64, 52

# (name in the results file, label, drawn on top last)
TOOLS = [
    ("chrome-devtools", "Chrome DevTools MCP"),
    ("playwright", "Playwright MCP"),
    ("cairn", "Dejo"),
]

THEMES = {
    "light": {
        "bg": "#ffffff",
        "ink": "#0b0d10",
        "muted": "#6b7280",
        "grid": "#eceef1",
        "chrome-devtools": "#b8bec7",
        "playwright": "#8a919c",
        "cairn": "#0b0d10",
    },
    "dark": {
        "bg": "#0d1117",
        "ink": "#f0f3f6",
        "muted": "#9198a1",
        "grid": "#21262d",
        "chrome-devtools": "#4a525c",
        "playwright": "#7d8590",
        "cairn": "#f0f3f6",
    },
}


def calls_per_run() -> dict[str, list[int]]:
    """Tool calls per fresh session, summed over the three tasks, for each tool."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0] * RUNS)
    for row in json.loads(SOURCE.read_text(encoding="utf-8")):
        totals[row["tool"]][row["run"] - 1] += row["tool_calls"]
    return dict(totals)


def draw(theme: dict[str, str], series: dict[str, list[int]]) -> str:
    top_value = max(max(values) for values in series.values())
    ceiling = ((top_value + 9) // 10) * 10
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def x(run: int) -> float:
        return LEFT + plot_w * run / (RUNS - 1)

    def y(value: float) -> float:
        return TOP + plot_h * (1 - value / ceiling)

    font = "font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif\""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" {font}>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="{theme["bg"]}"/>',
        f'<text x="{LEFT}" y="30" font-size="15" font-weight="600" fill="{theme["ink"]}">'
        "Tool calls per fresh session, three multi-step tasks</text>",
        f'<text x="{LEFT}" y="49" font-size="12" fill="{theme["muted"]}">'
        "Each run is a brand-new Claude chat. Lower is better.</text>",
    ]
    for step in range(0, ceiling + 1, 10):
        parts.append(
            f'<line x1="{LEFT}" x2="{LEFT + plot_w}" y1="{y(step):.1f}" y2="{y(step):.1f}" '
            f'stroke="{theme["grid"]}"/>'
        )
        parts.append(
            f'<text x="{LEFT - 10}" y="{y(step) + 4:.1f}" font-size="11" text-anchor="end" '
            f'fill="{theme["muted"]}">{step}</text>'
        )
    for run in range(RUNS):
        parts.append(
            f'<text x="{x(run):.1f}" y="{TOP + plot_h + 20}" font-size="11" '
            f'text-anchor="middle" fill="{theme["muted"]}">{run + 1}</text>'
        )
    parts.append(
        f'<text x="{LEFT + plot_w / 2:.1f}" y="{HEIGHT - 10}" font-size="11" '
        f'text-anchor="middle" fill="{theme["muted"]}">run</text>'
    )
    for name, label in TOOLS:
        values = series[name]
        colour = theme[name]
        mine = name == "cairn"
        points = " ".join(f"{x(run):.1f},{y(value):.1f}" for run, value in enumerate(values))
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{colour}" '
            f'stroke-width="{3 if mine else 2}" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        end = y(values[-1])
        parts.append(
            f'<text x="{x(RUNS - 1) + 12:.1f}" y="{end + 4:.1f}" font-size="12.5" '
            f'font-weight="{700 if mine else 500}" fill="{colour if not mine else theme["ink"]}">'
            f"{label} · {sum(values)} in total</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    series = calls_per_run()
    OUT.mkdir(parents=True, exist_ok=True)
    for mode, theme in THEMES.items():
        (OUT / f"benchmark-{mode}.svg").write_text(draw(theme, series), encoding="utf-8")
    print(f"wrote benchmark-light.svg and benchmark-dark.svg to {OUT}")


if __name__ == "__main__":
    main()
