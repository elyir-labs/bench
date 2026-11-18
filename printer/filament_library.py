"""The filament library for spool tags (design/spool-tags/, pick 6 A): SpoolmanDB, shipped with Bench in
tag_data/filaments.json.gz (tools/build-tag-data.py) and searched here, on the printer, so it works offline."""
import gzip
import json
import os
import re
from typing import Any, Dict, List, Optional

PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tag_data", "filaments.json.gz")
FIRST_BRANDS = ("Polymaker", "ELEGOO", "Sunlu", "eSun", "ANYCUBIC", "Prusament", "Bambu Lab", "Overture", "Creality")
RESULTS = 30

_products: Optional[List[Dict[str, Any]]] = None


def products() -> List[Dict[str, Any]]:
    global _products
    if _products is None:
        try:
            with gzip.open(PATH, "rt", encoding="utf-8") as f:
                _products = json.load(f)["products"]
        except (OSError, ValueError, KeyError):
            _products = []
    return _products


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9+]+", (text or "").lower()) if w]


def brands() -> List[str]:
    """The brand chips: the common ones first, then every other brand the library has."""
    have = sorted({p["b"] for p in products()}, key=str.lower)
    first = [b for b in FIRST_BRANDS if b in have]
    return first + [b for b in have if b not in first]


def search(q: str = "", brand: str = "", diameter: float = 1.75, limit: int = RESULTS) -> Dict[str, Any]:
    """Products whose brand, material, line or color names hold every word typed, with only this printer's
    diameter's colors. A color matching the words is marked, so "petg orange" lands on orange."""
    words = _words(q)
    out = []
    common = {b.lower() for b in FIRST_BRANDS}
    order = sorted(range(len(products())), key=lambda i: (products()[i]["b"].lower() not in common, i))
    for i in order:
        p = products()[i]
        if brand and p["b"].lower() != brand.lower():
            continue
        cols = [c for c in p["c"] if abs((c[2] or 1.75) - diameter) < 0.05]
        if not cols:
            continue
        head = _words(f"{p['b']} {p['m']} {p['p']}")
        colors = []
        for c in cols:
            names = _words(c[0])
            if all(any(h.startswith(w) for h in head + names) for w in words):
                colors.append({"name": c[0], "hex": c[1] or "888888", "weights": c[3] or [1000],
                               "hit": bool(words) and any(any(n.startswith(w) for n in names) for w in words)})
        if not colors:
            continue
        out.append({"id": i, "brand": p["b"], "material": p["m"], "line": p["p"], "nozzle": p.get("t"),
                    "bed": p.get("bt"), "density": p.get("d"), "colors": colors})
        if len(out) >= limit:
            break
    return {"results": out, "brands": brands() if not q and not brand else None}


def spool(product_id: int, color: str, weight: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The spool a library pick stands for, everything the formats need filled from the library."""
    try:
        p = products()[int(product_id)]
    except (IndexError, ValueError, TypeError):
        return None
    c = next((c for c in p["c"] if c[0] == color), None)
    if c is None:
        return None
    name = f"{p['p']} {c[0]}".strip() if p["p"] else c[0]
    weights = c[3] or [1000]
    return {"brand": p["b"], "material": p["m"], "name": name, "color": (c[1] or "888888").upper(),
            "weight": int(weight) if weight in weights else (1000 if 1000 in weights else weights[0]),
            "diameter": c[2] or 1.75, "nozzle": p.get("t"), "bed": p.get("bt"), "density": p.get("d"),
            "source": "library"}
