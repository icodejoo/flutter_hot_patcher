#!/usr/bin/env python3
"""
Benchmark report generator.
Reads spikes/benchmark/results/*.json → terminal table + results/report.html

Usage: python3 scripts/report.py
"""
import json
import pathlib
from typing import Optional

RESULTS_DIR = pathlib.Path(__file__).parent.parent / "results"

EXPECTED = [
    ("hotpatch",     "ios", "normal"),
    ("hotpatch",     "ios", "cpu"),
    ("hotpatch_aot", "ios", "none"),
    ("hotpatch_aot", "ios", "normal"),
    ("hotpatch_aot", "ios", "cpu"),
    ("shorebird",    "ios", "none"),
    ("shorebird",    "ios", "normal"),
    ("shorebird",    "ios", "cpu"),
    ("shorebird",    "android", "normal"),
    ("shorebird",    "android", "cpu"),
]

METRICS = [
    ("patch_size_bytes", "Patch Size",   lambda v: f"{v:,} B"),
    ("cold_start_ms",    "Cold Start",   lambda v: f"{v:.1f} ms"),
    ("greet_call_ns",    "greet() ns",   lambda v: f"{v} ns" if v else "N/A"),
    ("greet_call_us",    "greet() μs",   lambda v: f"{v:.1f} μs" if v else "N/A"),
    ("memory_rss_kb",    "RSS",          lambda v: f"{v:,} KB"),
    ("cpu_percent_peak", "CPU Peak",     lambda v: f"{v:.1f}%"),
]

COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948"]


def load_result(variant: str, platform: str, patch_type: str) -> Optional[dict]:
    p = RESULTS_DIR / f"{variant}_{platform}_{patch_type}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def fmt(result: Optional[dict], key: str, formatter) -> str:
    if result is None:
        return "N/A"
    v = result.get(key)
    if v is None:
        return "N/A"
    try:
        return formatter(v)
    except Exception:
        return str(v)


def print_table(rows: list) -> None:
    try:
        from rich.table import Table
        from rich.console import Console

        t = Table(title="Hot-Patch Benchmark Results", show_lines=True)
        t.add_column("Variant",   style="cyan")
        t.add_column("Platform",  style="magenta")
        t.add_column("PatchType", style="yellow")
        for _, col_name, _ in METRICS:
            t.add_column(col_name, justify="right")

        for variant, platform, patch_type, result in rows:
            t.add_row(
                variant, platform, patch_type,
                *[fmt(result, key, fmtr) for key, _, fmtr in METRICS],
            )
        Console().print(t)
    except ImportError:
        # Plain text fallback
        col_names = ["Variant", "Platform", "PatchType"] + [n for _, n, _ in METRICS]
        widths = [max(12, len(n)) for n in col_names]
        header = "  ".join(n.ljust(w) for n, w in zip(col_names, widths))
        print(header)
        print("-" * len(header))
        for variant, platform, patch_type, result in rows:
            cells = [variant, platform, patch_type] + \
                    [fmt(result, key, fmtr) for key, _, fmtr in METRICS]
            print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))


def build_html(rows: list) -> str:
    th_metrics = "".join(f"<th>{n}</th>" for _, n, _ in METRICS)

    html_rows = []
    for variant, platform, patch_type, result in rows:
        cells = ""
        for key, _, fmtr in METRICS:
            v = fmt(result, key, fmtr)
            cls = ' class="na"' if v == "N/A" else ""
            cells += f"<td{cls}>{v}</td>"
        html_rows.append(
            f"<tr><td>{variant}</td><td>{platform}</td><td>{patch_type}</td>{cells}</tr>"
        )

    labels = [f"{v}/{pl}/{pt}" for v, pl, pt, _ in rows]

    charts_html = ""
    for idx, (key, col_name, _) in enumerate(METRICS):
        data = []
        for _, _, _, result in rows:
            if result and result.get(key) is not None:
                data.append(result[key])
            else:
                data.append(None)
        color = COLORS[idx % len(COLORS)]
        chart_id = f"chart_{key}"
        charts_html += f"""
<h2>{col_name}</h2>
<canvas id="{chart_id}" height="80"></canvas>
<script>
new Chart(document.getElementById("{chart_id}"), {{
  type: "bar",
  data: {{
    labels: {json.dumps(labels)},
    datasets: [{{
      label: "{col_name}",
      data: {json.dumps(data)},
      backgroundColor: "{color}88",
      borderColor: "{color}",
      borderWidth: 1,
      spanGaps: false
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true }} }}
  }}
}});
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Hot-Patch Benchmark</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 1.5rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: 0.9rem; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
  th {{ background: #f8f8f8; text-align: center; font-weight: 600; }}
  td:nth-child(1), td:nth-child(2), td:nth-child(3) {{ text-align: left; }}
  .na {{ color: #bbb; }}
  canvas {{ max-width: 100%; margin-bottom: 1rem; }}
</style>
</head>
<body>
<h1>Hot-Patch Benchmark Results</h1>
<table>
  <tr><th>Variant</th><th>Platform</th><th>PatchType</th>{th_metrics}</tr>
  {"".join(html_rows)}
</table>
{charts_html}
</body>
</html>"""


def main() -> None:
    rows = [
        (variant, platform, patch_type, load_result(variant, platform, patch_type))
        for variant, platform, patch_type in EXPECTED
    ]

    found = sum(1 for *_, r in rows if r is not None)
    print(f"\nLoaded {found}/{len(rows)} result files ({len(rows) - found} N/A)\n")

    print_table(rows)

    html = build_html(rows)
    out = RESULTS_DIR / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML report → {out}")
    print("Open with: open spikes/benchmark/results/report.html")


if __name__ == "__main__":
    main()
