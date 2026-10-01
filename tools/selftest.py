#!/usr/bin/env python3
"""
Auto-test de la chaîne de montage : génère 6 images de synthèse + un mini scénario,
rend une vidéo 9:16 et lance le contrôle qualité. Aucune ressource externe requise.

  python3 tools/selftest.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "project", "_selftest")
FONT = os.path.join(ROOT, "assets", "fonts", "Montserrat-800.ttf")


def synth_images() -> list[str]:
    os.makedirs(TMP, exist_ok=True)
    sizes = [(1080, 1920), (1920, 1080), (1080, 1350), (1080, 1920), (1600, 1200), (1080, 1920)]
    labels = ["MARCHÉ", "PRODUIT", "LIVRAISON", "PAIEMENT", "SÉCURITÉ", "VENDEUR"]
    paths = []
    rng = np.random.default_rng(0)
    for i, ((w, h), lab) in enumerate(zip(sizes, labels)):
        base = np.zeros((h, w, 3), dtype=np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        base[..., 0] = 20 + 60 * (xx / w)
        base[..., 1] = 30 + 70 * (yy / h)
        base[..., 2] = 45 + 90 * (1 - xx / w)
        base += rng.normal(0, 6, base.shape)
        img = Image.fromarray(np.clip(base, 0, 255).astype("uint8"))
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(FONT, int(h * 0.055))
        d.rectangle([0, int(h * 0.42), w, int(h * 0.58)], fill=(255, 195, 0))
        d.text((w * 0.06, h * 0.46), lab, font=f, fill=(11, 20, 32))
        d.text((w * 0.06, h * 0.06), f"IMAGE {i+1} · {w}x{h}", font=ImageFont.truetype(FONT, int(h * 0.028)),
               fill=(255, 255, 255))
        p = os.path.join(TMP, f"img{i+1}.jpg")
        img.save(p, quality=92)
        paths.append(p)
    return paths


def pseudo_voice(path: str, base: float, dur: float, seed: int = 0) -> str:
    """Fausse voix au débit parole (syllabes) : sert à tester le calage des répliques."""
    import numpy as np
    sr = 48000
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    t = np.arange(n) / sr
    syll = np.zeros(n)
    pos = 0.0
    while pos < dur:                      # alternance syllabe / silence, comme de la parole
        d = float(rng.uniform(0.13, 0.26))
        s0, s1 = int(pos * sr), min(int((pos + d) * sr), n)
        if s1 > s0:
            env = np.hanning(max(s1 - s0, 2))
            f0 = base * float(rng.uniform(0.9, 1.15))
            seg = sum(np.sin(2 * np.pi * f0 * k * t[s0:s1]) / k
                      for k in (1, 2, 3, 5)) * env
            syll[s0:s1] += seg
        pos += d + float(rng.uniform(0.04, 0.12))
    syll /= max(float(np.max(np.abs(syll))), 1e-6)
    pcm = (syll * 0.7 * 32767).astype("<i2")
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1); fh.setsampwidth(2); fh.setframerate(sr)
        fh.writeframes(pcm.tobytes())
    return path


def dialogue_timeline() -> dict:
    """Scénario de test au format podcast : deux personnages qui se répondent."""
    plan = [
        ("AWA", "Je commande en ligne et je me fais arnaquer, encore", 3.0, "hook", "Le cauchemar du paiement en ligne"),
        ("MOUSSA", "Attends, tu as payé avant de vérifier le vendeur ?", 2.6, "body", ""),
        ("AWA", "Oui, et le vendeur a disparu le lendemain", 2.6, "body", ""),
        ("MOUSSA", "Sur elimarket, le vendeur est vérifié avant de publier", 3.2, "body", ""),
        ("AWA", "Et mon argent, il est protégé comment ?", 2.6, "body", ""),
        ("MOUSSA", "Il reste bloqué jusqu'à la réception du colis", 3.0, "body", ""),
        ("NARRATEUR", "Rejoins elimarket point africa, inscription gratuite", 3.2, "cta", "Rejoignez elimarket.africa"),
    ]
    scenes = []
    for i, (who, text, dur, style, onscreen) in enumerate(plan):
        # durée de la réplique cohérente avec sa longueur (comme un vrai enregistrement)
        vdur = round(max(1.0, len(text.split()) / 2.6 * 0.92), 2)
        dur = round(max(dur, vdur + 0.4), 2)   # un plan dure au moins sa réplique + 0,4 s
        vfile = pseudo_voice(os.path.join(TMP, f"voix{i:02d}_{who.lower()}.wav"),
                             {"AWA": 210.0, "MOUSSA": 120.0, "NARRATEUR": 165.0}[who], vdur, i + 1)
        scene = {
            "image": f"img{i % 6 + 1}.jpg",
            "dur": dur,
            "motion": "auto",
            "transition": "fade" if i % 2 else "cut",
            "sfx": "whoosh" if i % 3 == 2 else ("impact" if i == 0 else ""),
            "lines": [{"who": who, "text": text, "file": os.path.relpath(vfile, TMP),
                       "dur": vdur}],
        }
        if onscreen:
            scene["text"] = {"value": onscreen, "style": style, "emph": ["elimarket"]}
        scenes.append(scene)
    return {
        "meta": {"title": "Auto-test podcast", "handle": "@elimarket.africa",
                 "keywords": ["vérifié", "protégé", "colis"],
                 "brand": {"accent": "#FFC300"}},
        "cast": {
            "AWA": {"voice": "féminine, 26 ans, énervée mais complice", "gender": "feminine",
                    "color": "#7ED0FF"},
            "MOUSSA": {"voice": "masculine, 30 ans, posée et rassurante", "gender": "masculine",
                       "color": "#FFC300"},
            "NARRATEUR": {"voice": "neutre, claire", "gender": "masculine", "color": "#FFFFFF"},
        },
        "audio": {"music": os.path.relpath(os.path.join(TMP, "bed.wav"), TMP),
                  "music_gain_db": -14.0},
        "subtitles": {"enabled": True, "max_words": 4, "show_speaker": True, "max_tempo": 1.18},
        "scenes": scenes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-test de la chaîne de montage")
    ap.add_argument("--dialogue", action="store_true",
                    help="tester le format podcast (personnages + répliques)")
    args = ap.parse_args()
    print("== 1/4 Images de test ==")
    imgs = synth_images()
    print(f"   {len(imgs)} images générées")

    print("== 2/4 Effets sonores + lit musical ==")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sfx.py")], check=True)
    music = os.path.join(TMP, "bed.wav")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_music.py"),
                    "--dur", "14", "--bpm", "112", "--key", "A", "--style", "urban",
                    "--out", music], check=True)

    print("== 3/4 Scénario de test + rendu ==")
    timeline = dialogue_timeline() if args.dialogue else {
        "meta": {"title": "Auto-test moteur de montage", "handle": "@elimarket.africa",
                 "keywords": ["confiance", "vendeurs", "afrique"],
                 "brand": {"accent": "#FFC300"}},
        "audio": {"music": os.path.relpath(music, TMP), "music_gain_db": -13.5},
        "subtitles": {"enabled": True, "font": "Montserrat", "body_font": "Inter", "max_words": 4},
        "scenes": [
            {"image": "img1.jpg", "dur": 2.4, "motion": "zoom_in", "transition": "cut",
             "sfx": "impact",
             "text": {"value": "Le marché de confiance", "style": "hook", "emph": ["confiance"]},
             "vo": "Le marché de confiance en Afrique, ça existe déjà"},
            {"image": "img2.jpg", "dur": 2.2, "motion": "pan_right", "transition": "fade",
             "sfx": "whoosh",
             "text": {"value": "Des milliers de produits", "style": "body", "emph": ["produits"]},
             "vo": "Des milliers de produits vérifiés près de chez vous, livrés partout"},
            {"image": "img3.jpg", "dur": 2.0, "motion": "push_soft", "transition": "cut",
             "text": {"value": "Paiement sécurisé", "style": "body", "emph": ["sécurisé"]},
             "vo": "Paiement sécurisé et livraison suivie"},
            {"image": "img4.jpg", "dur": 2.4, "motion": "tilt_up", "transition": "slideleft",
             "sfx": "riser",
             "text": {"value": "Des vendeurs vérifiés", "style": "body", "emph": ["vendeurs"]},
             "vo": "Chaque vendeur est vérifié, chaque avis est réel"},
            {"image": "img5.jpg", "dur": 2.2, "motion": "zoom_out", "transition": "cut",
             "text": {"value": "Zéro arnaque", "style": "body", "emph": ["arnaques"]},
             "vo": "Fini les arnaques et les faux profils"},
            {"image": "img6.jpg", "dur": 2.6, "motion": "parallax_push", "transition": "fade",
             "sfx": "impact",
             "text": {"value": "Rejoignez elimarket.africa", "style": "cta", "emph": ["elimarket"]},
             "vo": "Créez votre compte gratuitement, publiez, vendez en toute sérénité"},
        ],
    }
    tl_path = os.path.join(TMP, "timeline.json")
    with open(tl_path, "w", encoding="utf-8") as fh:
        json.dump(timeline, fh, ensure_ascii=False, indent=2)

    out = os.path.join(TMP, "out")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "render.py"), tl_path,
                    "--aspects", "9:16", "--out", out], check=True)

    print("== 4/4 Contrôle qualité ==")
    res = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "qc.py"), out, "--frames"])
    print("\nAuto-test :", "SUCCÈS" if res.returncode == 0 else "ÉCHEC (voir ci-dessus)")
    sys.exit(res.returncode)


if __name__ == "__main__":
    try:
        main()
    finally:
        pass
