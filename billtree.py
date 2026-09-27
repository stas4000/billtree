#!/usr/bin/env python3
"""billtree: per-resource AWS bill breakdown from a Cost and Usage Report (CUR).

One pass, streaming, standard library only. Reads legacy CUR and CUR 2.0 CSV
exports (.csv or .csv.gz, files or folders) and builds the tree
account > service > region > resource. Prints the top of the tree, writes a
compact JSON an AI agent can read in one prompt, and a self-contained HTML
treemap.

    python3 billtree.py ./cur-export/ --top 15
    python3 billtree.py cur.csv.gz --json bill.json --html bill.html

MIT license.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import os
import sys
from pathlib import Path

__version__ = "0.1.0"

# Column aliases: CUR 2.0 (snake_case) first, then legacy CUR (slash names).
COLUMNS = {
    "account": ("line_item_usage_account_id", "lineItem/UsageAccountId"),
    "service": ("line_item_product_code", "lineItem/ProductCode"),
    "region": ("product_region_code", "product/region", "product_region"),
    "resource": ("line_item_resource_id", "lineItem/ResourceId"),
    "cost": ("line_item_unblended_cost", "lineItem/UnblendedCost"),
    "type": ("line_item_line_item_type", "lineItem/LineItemType"),
}
LEVELS = ("account", "service", "region", "resource")
NO_RESOURCE = "(no resource id)"
NO_REGION = "(global)"

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return open(path, newline="", encoding="utf-8")


def find_files(inputs: list[str]) -> list[Path]:
    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.name.endswith((".csv", ".csv.gz")))
        elif p.exists():
            out.append(p)
        else:
            raise SystemExit(f"billtree: no such file or folder: {item}")
    if not out:
        raise SystemExit("billtree: no .csv or .csv.gz files found")
    return out


def _index(header: list[str]) -> dict[str, int | None]:
    pos = {name: i for i, name in enumerate(header)}
    idx: dict[str, int | None] = {}
    for key, names in COLUMNS.items():
        idx[key] = next((pos[n] for n in names if n in pos), None)
    missing = [k for k in ("service", "cost") if idx[k] is None]
    if missing:
        raise SystemExit(f"billtree: not a CUR file, missing column(s) for: {', '.join(missing)}")
    return idx


def aggregate(files: list[Path]) -> tuple[dict, dict]:
    """Return (costs keyed by (account, service, region, resource), stats)."""
    costs: dict[tuple, float] = {}
    rows = 0
    skipped = 0
    for path in files:
        with _open(path) as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header is None:
                continue
            idx = _index(header)
            ia, isv, irg, irs, ic = (idx[k] for k in ("account", "service", "region", "resource", "cost"))
            for row in reader:
                rows += 1
                try:
                    cost = float(row[ic])
                except (ValueError, IndexError):
                    skipped += 1
                    continue
                if cost == 0.0:
                    continue
                key = (
                    row[ia] if ia is not None else "(account)",
                    row[isv] or "(unknown)",
                    (row[irg] if irg is not None else "") or NO_REGION,
                    (row[irs] if irs is not None else "") or NO_RESOURCE,
                )
                costs[key] = costs.get(key, 0.0) + cost
    return costs, {"files": len(files), "rows": rows, "skipped": skipped}


def build_tree(costs: dict) -> dict:
    root: dict = {"name": "total", "cost": 0.0, "children": {}}
    for key, cost in costs.items():
        node = root
        node["cost"] += cost
        for part in key:
            node = node["children"].setdefault(part, {"name": part, "cost": 0.0, "children": {}})
            node["cost"] += cost
    return root


def to_plain(node: dict, depth: int = 0, top: int | None = None) -> dict:
    """Sorted, rounded tree. `top` keeps the largest children per node, rest folded."""
    kids = sorted(node["children"].values(), key=lambda n: -n["cost"])
    out = {"name": node["name"], "cost": round(node["cost"], 4)}
    if kids:
        shown = kids if top is None else kids[:top]
        rest = kids[len(shown):]
        children = [to_plain(k, depth + 1, top) for k in shown]
        if rest:
            children.append({"name": f"({len(rest)} more)", "cost": round(sum(k["cost"] for k in rest), 4)})
        out["level"] = LEVELS[depth] if depth < len(LEVELS) else "leaf"
        out["children"] = children
    return out


def top_resources(costs: dict, n: int) -> list[dict]:
    rows = sorted(costs.items(), key=lambda kv: -kv[1])[:n]
    return [
        {"account": a, "service": s, "region": r, "resource": res, "cost": round(c, 4)}
        for (a, s, r, res), c in rows
    ]


def render_text(costs: dict, total: float, n: int) -> str:
    lines = [f"Total: ${total:,.2f} across {len(costs):,} resource lines", ""]
    for i, r in enumerate(top_resources(costs, n), 1):
        share = 100 * r["cost"] / total if total else 0
        lines.append(f"{i:>3}. ${r['cost']:>12,.2f}  {share:5.1f}%  {r['service']:<22} {r['region']:<14} {r['resource']}")
    return "\n".join(lines)


def squarify(items: list[tuple[str, float, object]], x: float, y: float, w: float, h: float) -> list:
    """Squarified treemap layout. items: (label, value, payload), value > 0."""
    items = [it for it in items if it[1] > 0]
    total = sum(v for _, v, _ in items)
    if not items or total <= 0 or w <= 0 or h <= 0:
        return []
    scale = w * h / total
    rects: list = []
    queue = [(lbl, v * scale, p) for lbl, v, p in sorted(items, key=lambda t: -t[1])]

    def worst(row: list, side: float) -> float:
        s = sum(a for _, a, _ in row)
        return max(max(side * side * a / (s * s), (s * s) / (side * side * a)) for _, a, _ in row)

    while queue:
        side = min(w, h)
        row = [queue.pop(0)]
        while queue and worst(row + [queue[0]], side) <= worst(row, side):
            row.append(queue.pop(0))
        s = sum(a for _, a, _ in row)
        if w >= h:
            cw = s / h
            cy = y
            for lbl, a, p in row:
                ch = a / cw
                rects.append((lbl, x, cy, cw, ch, p))
                cy += ch
            x += cw
            w -= cw
        else:
            rh = s / w
            cx = x
            for lbl, a, p in row:
                cwid = a / rh
                rects.append((lbl, cx, y, cwid, rh, p))
                cx += cwid
            y += rh
            h -= rh
    return rects


PALETTE = ["#e4572e", "#29335c", "#f3a712", "#669bbc", "#a8c686", "#8e6c8a", "#3d9970", "#c05746", "#4f6d7a", "#d4a373"]


def render_html(costs: dict, total: float, width: int = 1200, height: int = 760) -> str:
    by_service: dict[str, list] = {}
    for (a, s, r, res), c in costs.items():
        by_service.setdefault(s, []).append((res, c, (a, s, r, res)))
    services = [(s, sum(c for _, c, _ in v), s) for s, v in by_service.items()]
    colors = {s: PALETTE[i % len(PALETTE)] for i, (s, _, _) in enumerate(sorted(services, key=lambda t: -t[1]))}
    svg: list[str] = []
    for svc, sx, sy, sw, sh, _ in squarify(services, 0, 0, width, height):
        for res, x, y, w, h, key in squarify(by_service[svc], sx + 1, sy + 18, sw - 2, sh - 19):
            c = costs[key]
            tip = html.escape(f"{svc} | {key[2]} | {res} | ${c:,.2f}")
            svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w-1,0):.1f}" height="{max(h-1,0):.1f}" fill="{colors[svc]}" fill-opacity="0.85"><title>{tip}</title></rect>')
            if w > 90 and h > 22:
                label = html.escape(res if len(res) < w / 7 else "..." + res[-int(w / 7) + 3:])
                svg.append(f'<text x="{x+4:.1f}" y="{y+15:.1f}" class="r">{label}</text>')
        if sw > 60:
            share = 100 * sum(c for _, c, _ in by_service[svc]) / total
            svg.append(f'<text x="{sx+4:.1f}" y="{sy+13:.1f}" class="s">{html.escape(svc)} {share:.1f}%</text>')
    return f"""<!doctype html><meta charset="utf-8"><title>billtree ${total:,.2f}</title>
<style>body{{font:14px system-ui,sans-serif;background:#111;color:#eee;margin:20px}}
text.s{{font-weight:700;fill:#fff}}text.r{{fill:#fff;font-size:11px}}rect:hover{{fill-opacity:1}}</style>
<h1>AWS bill ${total:,.2f} &middot; {len(costs):,} resource lines</h1>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{''.join(svg)}</svg>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="billtree", description=__doc__.split("\n\n")[0])
    ap.add_argument("inputs", nargs="+", help="CUR .csv / .csv.gz files or folders")
    ap.add_argument("--top", type=int, default=15, help="resources to print (default 15)")
    ap.add_argument("--json", metavar="PATH", help="write the tree as JSON for an AI agent")
    ap.add_argument("--json-top", type=int, default=25, help="children kept per node in JSON (default 25)")
    ap.add_argument("--html", metavar="PATH", help="write a self-contained HTML treemap")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    files = find_files(a.inputs)
    costs, stats = aggregate(files)
    total = sum(costs.values())
    print(render_text(costs, total, a.top))
    if a.json:
        doc = {
            "total": round(total, 4),
            "stats": {**stats, "resources": len(costs)},
            "top_resources": top_resources(costs, a.top),
            "tree": to_plain(build_tree(costs), top=a.json_top),
        }
        Path(a.json).write_text(json.dumps(doc, separators=(",", ":")))
        print(f"\nJSON: {a.json} ({os.path.getsize(a.json):,} bytes)")
    if a.html:
        Path(a.html).write_text(render_html(costs, total))
        print(f"HTML: {a.html}")
    if stats["skipped"]:
        print(f"note: {stats['skipped']} rows had no numeric cost and were skipped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
