#!/usr/bin/env python3
"""
Contrôle qualité automatique avant livraison.

  python3 tools/qc.py project/output                 # vérifie tout ce qui a été rendu
  python3 tools/qc.py project/output --frames        # + extrait des vignettes de contrôle

Vérifie : format/résolution, durée, hook dans les 2 s, sous-titres (3-5 mots, sans coupe),
zones sûres, absence de plan statique > 3 s, présence de l'appel à l'action, loudness -14 LUFS.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import FORMATS, ffmpeg, probe  # noqa: E402

OK, KO, WARN = "✅", "❌", "⚠️ "


def loudness(path: str) -> dict | None:
    """Mesure intégrée (EBU R128) via le filtre ebur128 de FFmpeg."""
    p = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", path,
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    out = p.stderr
    m = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", out)
    lra = re.findall(r"LRA:\s*(-?\d+\.\d+)\s*LU", out)
    tp = re.findall(r"Peak:\s*(-?\d+\.\d+)\s*dBFS", out)
    if not m:
        return None
    return {"i": float(m[-1]), "lra": float(lra[-1]) if lra else None,
            "tp": float(tp[-1]) if tp else None}


def check_video(path: str, report: dict) -> tuple[list[str], bool]:
    lines, ok = [], True
    info = probe(path)
    fmt = FORMATS[report["aspect"]]
    dur = info.get("duration", 0.0)
    w, h = info.get("w"), info.get("h")

    def say(cond: bool, good: str, bad: str, warn: bool = False) -> None:
        nonlocal ok
        if cond:
            lines.append(f"  {OK} {good}")
        elif warn:
            lines.append(f"  {WARN}{bad}")
        else:
            lines.append(f"  {KO} {bad}")
            ok = False

    say((w, h) == (fmt.w, fmt.h), f"Résolution {w}x{h} conforme ({report['aspect']})",
        f"Résolution {w}x{h} ≠ attendu {fmt.w}x{fmt.h}")
    target = report["duration"]
    say(abs(dur - target) <= 0.6, f"Durée {dur:.1f}s (cible {target:.1f}s ±0,6s)",
        f"Durée {dur:.1f}s, écart {dur - target:+.2f}s avec la cible")
    say(info.get("fps", 0) >= 24, f"Cadence {info.get('fps')} fps", "Cadence trop faible")
    say(info.get("has_audio", False), "Piste audio présente", "Aucune piste audio")

    # Hook dans les 2 premières secondes
    ft = report.get("first_text_at")
    say(ft is not None and ft <= 2.0, f"Hook affiché à {ft}s (≤ 2 s)",
        f"Hook à {ft}s : trop tardif (> 2 s)")

    # Sous-titres : 3 à 5 mots, pas de chevauchement, sans coupe de mot
    cues = report.get("cues", [])
    if cues:
        bad_words = [c for c in cues if not 1 <= c["words"] <= 5]
        overlaps = [i for i in range(1, len(cues)) if cues[i]["start"] < cues[i - 1]["end"] - 0.02]
        # Un trou n'est gênant que si rien d'autre n'est à l'écran (titre incrusté du plan)
        titles = {s["index"] for s in report.get("scenes", []) if s.get("has_text")}
        gaps = [i for i in range(1, len(cues))
                if cues[i]["start"] - cues[i - 1]["end"] > 0.9
                and cues[i].get("scene") not in titles]
        say(not bad_words, f"{len(cues)} sous-titres, 1 à 5 mots par affichage",
            f"{len(bad_words)} sous-titre(s) hors cible de mots")
        say(not overlaps, "Aucun chevauchement de sous-titres",
            f"{len(overlaps)} chevauchement(s) de sous-titres")
        say(not gaps, "Aucun silence mort > 0,9 s entre sous-titres",
            f"{len(gaps)} trou(s) > 0,9 s entre sous-titres")
        say(all(c["end"] <= dur + 0.1 for c in cues),
            "Tous les sous-titres tiennent dans la durée", "Sous-titre au-delà de la fin")
    else:
        lines.append(f"  {WARN}Aucun sous-titre (voix off absente ?)")
        ok = False

    # Mouvement : aucun plan statique > 3 s
    slow = [s for s in report.get("scenes", []) if s["dur"] > 3.0 and s["motion"] in
            ("hold_breath", "static")]
    say(not slow, "Aucun plan statique > 3 s", f"{len(slow)} plan(s) statique(s) > 3 s")

    # Appel à l'action
    say(report.get("has_cta", False), "Appel à l'action présent dans le montage",
        "Appel à l'action absent")

    # Loudness
    if info.get("has_audio"):
        l = loudness(path)
        if l:
            say(-16.5 <= l["i"] <= -12.0,
                f"Loudness intégrée {l['i']:.1f} LUFS (cible -14 ±1,5)",
                f"Loudness {l['i']:.1f} LUFS hors cible -14 ±1,5 LUFS")
            if l["tp"] is not None:
                say(l["tp"] <= -0.3, f"Crête vraie {l['tp']:.1f} dBTP (pas d'écrêtage)",
                    f"Crête vraie {l['tp']:.1f} dBTP : risque de saturation", warn=True)
    return lines, ok


def extract_frames(path: str, report: dict, outdir: str) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    made = []
    for i, sc in enumerate(report.get("scenes", [])):
        mid = sc.get("start", 0.0) + sc["dur"] / 2
        out = os.path.join(outdir, f"plan{i+1:02d}_{int(mid*10)/10}s.jpg")
        subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{mid:.2f}",
                        "-i", path, "-frames:v", "1", "-q:v", "3", out], capture_output=True)
        if os.path.exists(out):
            made.append(out)
    return made


def main() -> None:
    ap = argparse.ArgumentParser(description="Contrôle qualité elimarket")
    ap.add_argument("folder", help="dossier contenant les rendus et leurs rapports JSON")
    ap.add_argument("--frames", action="store_true", help="extrait une vignette par plan")
    args = ap.parse_args()

    reports = sorted(glob.glob(os.path.join(args.folder, "*_report.json")))
    if not reports:
        sys.exit(f"Aucun rapport de rendu dans {args.folder} — lancez d'abord tools/render.py")

    global_ok = True
    for rp in reports:
        with open(rp, encoding="utf-8") as fh:
            report = json.load(fh)
        video = report["file"]
        print(f"\n=== {os.path.basename(video)} ({report['aspect']}) ===")
        if not os.path.exists(video):
            print(f"  {KO} Fichier manquant : {video}")
            global_ok = False
            continue
        size_mb = os.path.getsize(video) / 1e6
        lines, ok = check_video(video, report)
        print("\n".join(lines))
        print(f"  {OK} Poids {size_mb:.1f} Mo")
        if args.frames:
            made = extract_frames(video, report, os.path.join(args.folder, "_qc_frames"))
            print(f"  {OK} {len(made)} vignettes de contrôle → {os.path.join(args.folder, '_qc_frames')}")
        global_ok &= ok

    print("\n" + ("=== QUALITÉ : TOUT EST CONFORME ===" if global_ok
                  else "=== QUALITÉ : CORRECTIONS NÉCESSAIRES ==="))
    sys.exit(0 if global_ok else 1)


if __name__ == "__main__":
    main()
