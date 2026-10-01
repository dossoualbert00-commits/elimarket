#!/usr/bin/env python3
"""
Auto-test de la chaîne de montage : génère 6 images de synthèse + un mini scénario,
rend une vidéo 9:16 et lance le contrôle qualité. Aucune ressource externe requise.

  python3 tools/selftest.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

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


def main() -> None:
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
    timeline = {
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
