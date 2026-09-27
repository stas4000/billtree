#!/usr/bin/env python3
"""Build the motion-explainer film page from the benchmark's own output.

    python3 video/make_film.py /tmp/billtree-bench/cur.csv.gz bench.json film.html film.json
Then: RACE_HTML=film.html render.sh film.json film.mp4 (the jev-oss-loop-video kit).
"""
import base64, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import billtree

cur, bench, out_html, out_json = sys.argv[1:5]
b = json.load(open(bench))
costs, stats = billtree.aggregate([Path(cur)])
total = sum(costs.values())
by = {}
for key, c in costs.items():
    by.setdefault(key[1], []).append((key[3], c, key))
svcs = sorted(((s, sum(c for _, c, _ in v), s) for s, v in by.items()), key=lambda t: -t[1])
X0, Y0, W, H = 70, 360, 940, 690
rects = []
for si, (svc, sx, sy, sw, sh, _) in enumerate(billtree.squarify(svcs, X0, Y0, W, H)):
    order = [s for s, _, _ in svcs].index(svc)
    for res, x, y, w, h, key in billtree.squarify(by[svc], sx + 2, sy + 2, sw - 4, sh - 4):
        rects.append([round(x, 1), round(y, 1), round(w, 1), round(h, 1), order, round(costs[key], 2)])
rects.sort(key=lambda r: -r[5])
top = rects[0]
svc_labels = []
for svc, sx, sy, sw, sh, _ in billtree.squarify(svcs, X0, Y0, W, H):
    if sw > 230 and sh > 60:
        share = 100 * sum(c for _, c, _ in by[svc]) / total
        svc_labels.append([svc.replace("Amazon", "").replace("AWS", ""), round(sx + 10, 1), round(sy + 10, 1), f"{share:.0f}%"])
data = {
    "rows": stats["rows"], "resources": len(costs), "seconds": b["elapsed_s"], "mb": b["csv_mb"],
    "ram": b["peak_rss_mb"], "json_kb": b["json_kb"], "total": f"${total:,.2f}",
    "top": {"rect": top[:4], "cost": f"${top[5]:,.0f}", "share": f"{100 * top[5] / total:.1f}%"},
    "rects": rects, "labels": svc_labels,
}
Path(out_json).write_text(json.dumps(data, separators=(",", ":")))
fonts = {"SG": "/home/username/decisionbench/video/fonts/SpaceGrotesk.ttf", "JB": "/home/username/scriptcut/video/fonts/JetBrainsMono.ttf"}
face = "".join(f'@font-face{{font-family:"{k}";src:url(data:font/ttf;base64,{base64.b64encode(open(p,"rb").read()).decode()}) format("truetype");font-weight:300 800}}' for k, p in fonts.items())
Path(out_html).write_text((Path(__file__).parent / "film.tpl.html").read_text().replace("/*FONTS*/", face))
print(json.dumps({k: v for k, v in data.items() if k not in ("rects", "labels")}))
