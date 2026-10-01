#!/usr/bin/env python3
"""
Maquette de rythme (« animatic ») : rend la bande-son et le minutage réels avant que
tous les visuels soient disponibles.

Les images manquantes sont remplacées par une plaque de contrôle, afin de valider
le calage des voix, les sous-titres, les coupes et la durée — sans jamais faire
passer un visuel provisoire pour un visuel final.

  python3 tools/maquette.py project/timeline.regles_p2.json
  python3 tools/maquette.py project/timeline.regles_complet.json --aspects 9:16
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from render import render  # noqa: E402

PLATE = os.path.join(ROOT, "project", "_preview", "plate.png")


def main() -> None:
    ap = argparse.ArgumentParser(description="Maquette de rythme (visuels provisoires)")
    ap.add_argument("timeline")
    ap.add_argument("--aspects", default="9:16")
    ap.add_argument("--out", default=os.path.join(ROOT, "project", "_preview", "output"))
    args = ap.parse_args()

    if not os.path.exists(PLATE):
        sys.exit(f"Plaque de contrôle absente : {PLATE}")

    with open(args.timeline, encoding="utf-8") as fh:
        raw = json.load(fh)
    base = os.path.dirname(os.path.abspath(args.timeline))

    missing = []
    for sc in raw["scenes"]:
        p = sc["image"]
        full = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
        if not os.path.exists(full):
            missing.append(p)
            sc["image"] = os.path.relpath(PLATE, base)

    out_tl = os.path.join(os.path.dirname(args.timeline),
                          "_preview_" + os.path.basename(args.timeline))
    with open(out_tl, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)

    print(f"▸ Maquette : {len(missing)} visuel(s) remplacé(s) par la plaque de contrôle")
    if missing:
        print("   à fournir : " + ", ".join(sorted(set(missing))))
    render(out_tl, [a.strip() for a in args.aspects.split(",")], os.path.abspath(args.out))
    print(f"▸ Maquette prête : {args.out}  (à valider, pas à publier)")


if __name__ == "__main__":
    main()
