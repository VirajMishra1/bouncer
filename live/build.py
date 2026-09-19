#!/usr/bin/env python3
"""Inline scenario.json into index.src.html -> index.html (single file, works offline)."""
import json, pathlib
root = pathlib.Path(__file__).parent
scenario = json.dumps(json.loads((root / "scenario.json").read_text()), indent=1).replace("</", "<\\/")
html = (root / "index.src.html").read_text().replace("__SCENARIO__", scenario)
(root / "index.html").write_text(html)
print("built", root / "index.html", len(html), "bytes")
