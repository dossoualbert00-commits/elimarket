#!/usr/bin/env python3
"""
elimarket — Moteur de montage vidéo (FFmpeg + ASS).

Entrée  : un fichier "timeline" JSON décrivant le découpage validé.
Sortie  : une vidéo par format demandé (9:16, 4:5, 1:1, 16:9) + .srt + rapport de rendu.

Principes appliqués (standards pro) :
  - mouvement permanent : aucun plan statique > 3 s (les "holds" longs deviennent des push lents) ;
  - images verticales en plein cadre, images horizontales composées sur fond flouté (jamais étirées) ;
  - sous-titres incrustés 3 à 5 mots, mot-clé surligné, dans la zone sûre de chaque plateforme ;
  - musique duckée sous la voix off (~-18 dB), voix normalisée à -14 LUFS ;
  - coupes sur le temps fort, transitions cohérentes.

Usage :
  python3 tools/render.py project/timeline.json
  python3 tools/render.py project/timeline.json --aspects 9:16,1:1 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(ROOT, "assets", "fonts")

# ----------------------------------------------------------------------------
# Formats cibles : résolution + zones sûres (px) où le texte reste lisible
# ----------------------------------------------------------------------------
@dataclass
class Format:
    name: str
    w: int
    h: int
    top: int        # marge haute à ne pas franchir (pseudo, barre YT…)
    bottom: int     # marge basse (UI TikTok/Reels, légende)
    side: int       # marge latérale
    sub_y: float    # position verticale des sous-titres (fraction de la hauteur)


FORMATS = {
    "9:16": Format("9:16", 1080, 1920, 230, 430, 90, 0.715),
    "4:5":  Format("4:5", 1080, 1350, 130, 300, 80, 0.700),
    "1:1":  Format("1:1", 1080, 1080, 110, 250, 80, 0.690),
    "16:9": Format("16:9", 1920, 1080, 90, 150, 140, 0.680),
}

# Durée de transition par type (secondes)
TRANSITIONS = {"cut": 0.0, "fade": 0.30, "dissolve": 0.40, "slideleft": 0.30,
               "slideright": 0.30, "wipeup": 0.30, "circleopen": 0.35, "smoothleft": 0.35}

# ----------------------------------------------------------------------------
# Mouvements de caméra : (zoom initial, zoom final, pan X 0-1, pan Y 0-1)
# Le pan est exprimé en fraction de l'espace disponible à zoom final.
# ----------------------------------------------------------------------------
MOTIONS = {
    "zoom_in":       (1.00, 1.10, 0.50, 0.50),
    "zoom_out":      (1.10, 1.00, 0.50, 0.50),
    "push_soft":     (1.00, 1.05, 0.50, 0.50),
    "pull_soft":     (1.05, 1.00, 0.50, 0.50),
    "pan_right":     (1.12, 1.12, 0.12, 0.50),
    "pan_left":      (1.12, 1.12, 0.88, 0.50),
    "tilt_up":       (1.12, 1.12, 0.50, 0.85),
    "tilt_down":     (1.12, 1.12, 0.50, 0.15),
    "dolly_diag":    (1.05, 1.16, 0.22, 0.70),
    "dolly_diag_rev": (1.16, 1.06, 0.72, 0.25),
    "parallax_push": (1.00, 1.13, 0.46, 0.54),
    "hold_breath":   (1.03, 1.045, 0.50, 0.50),
}
# Rotation automatique pour alterner les mouvements et éviter la monotonie
AUTO_CYCLE = ["zoom_in", "pan_right", "push_soft", "tilt_up", "zoom_out",
              "pan_left", "parallax_push", "tilt_down", "dolly_diag", "pull_soft"]

MAX_STATIC = 3.0  # s — au-delà, un plan doit bouger


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------
def run(cmd: list[str], quiet: bool = True) -> None:
    """Exécute FFmpeg et remonte l'erreur utile en cas d'échec."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-18:])
        raise RuntimeError(f"Échec commande:\n{' '.join(cmd[:6])} …\n{tail}")


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg") or shutil.which(
        "ffmpeg", path=os.path.expanduser("~/.local/bin"))
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    if not exe:
        sys.exit("FFmpeg introuvable — lancez `bash tools/bootstrap.sh`.")
    return exe


def probe(path: str) -> dict:
    """Métadonnées d'un média (via ffmpeg -i, ffprobe absent du binaire statique)."""
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    out = p.stderr
    info: dict = {"path": path}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Stream #\d+:\d+.*?: Video: .*?, (\d+)x(\d+)", out)
    if m:
        info["w"], info["h"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?) fps", out)
    if m:
        info["fps"] = float(m.group(1))
    info["has_audio"] = "Stream #0:1" in out and "Audio:" in out
    return info


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "video"


def hex_to_ass(color: str, alpha: str = "00") -> str:
    """#FFC300 -> &HAABBGGRR (format ASS)."""
    c = color.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


# ----------------------------------------------------------------------------
# Timeline
# ----------------------------------------------------------------------------
@dataclass
class Scene:
    index: int
    image: str
    dur: float
    motion: str = "auto"
    transition: str = "cut"
    text: str = ""
    text_style: str = "body"        # hook | body | cta | kicker
    emph: list[str] = field(default_factory=list)
    vo: str = ""                    # texte de la voix off (sert aux sous-titres)
    vo_file: str = ""
    sfx: str = ""                   # whoosh | riser | impact | none
    lines: list[dict] = field(default_factory=list)           # répliques (podcast / fiction)
    lines_planned: list[dict] = field(default_factory=list)   # répliques placées sur la timeline
    start: float = 0.0              # calculé
    motion_resolved: str = ""


def load_timeline(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    base = os.path.dirname(os.path.abspath(path))

    def resolve(p: str) -> str:
        if not p:
            return ""
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))

    meta = raw.get("meta", {})
    audio = raw.get("audio", {}) or {}
    subs = raw.get("subtitles", {}) or {}
    scenes = []
    for i, s in enumerate(raw["scenes"], start=1):
        t = s.get("text") or {}
        scenes.append(Scene(
            index=i,
            image=resolve(s["image"]),
            dur=float(s["dur"]),
            motion=s.get("motion", "auto"),
            transition=s.get("transition", "cut"),
            text=t.get("value", s.get("onscreen", "")),
            text_style=t.get("style", "body"),
            emph=[w.lower() for w in (t.get("emph") or [])],
            vo=s.get("vo", ""),
            vo_file=resolve(s.get("vo_file", "")),
            sfx=s.get("sfx", ""),
            lines=[{"who": ln.get("who", ""),
                    "text": ln.get("text", ""),
                    "file": resolve(ln.get("file", "")),
                    "dur": float(ln.get("dur", 0) or 0),
                    "gain_db": float(ln.get("gain_db", 0) or 0)} for ln in (s.get("lines") or [])],
        ))
    # Mouvement résolu + garde-fou anti-plan-statique
    for i, sc in enumerate(scenes):
        m = sc.motion
        if m == "auto":
            m = AUTO_CYCLE[i % len(AUTO_CYCLE)]
        if m not in MOTIONS:
            raise SystemExit(f"Plan {sc.index} : mouvement inconnu « {m} ».")
        if sc.dur > MAX_STATIC and max(abs(MOTIONS[m][1] - MOTIONS[m][0]),
                                       abs(MOTIONS[m][2] - 0.5), abs(MOTIONS[m][3] - 0.5)) < 0.01:
            m = "push_soft"
        sc.motion_resolved = m
    # Décalage temporel : la transition d'un plan est celle qui l'amène à l'écran
    # (entrante), les plans se chevauchent donc de cette durée.
    t = 0.0
    for i, sc in enumerate(scenes):
        if i > 0:
            t -= TRANSITIONS.get(sc.transition, 0.0)   # chevauchement de la transition
        sc.start = t
        t += sc.dur
    total = sum(s.dur for s in scenes) - sum(
        TRANSITIONS.get(s.transition, 0.0) for s in scenes[1:])
    plan_dialogue(scenes, subs)
    cast = raw.get("cast") or {}
    for who in {ln["who"] for sc in scenes for ln in sc.lines}:
        if who and who not in cast:
            cast[who] = {}
    return {
        "meta": meta, "audio": audio, "subtitles": subs, "scenes": scenes, "cast": cast,
        "total": round(total, 3),
        "voiceover": resolve(audio.get("voiceover", "")),
        "music": resolve(audio.get("music", "")),
    }


DIALOGUE_WARNINGS: list[str] = []


def plan_dialogue(scenes: list[Scene], sub_cfg: dict) -> None:
    """
    Place les répliques d'un plan (format podcast / fiction) sur la timeline.

    - la durée réelle du fichier audio prime ; sinon on estime 2,6 mots/s ;
    - si les répliques ne rentrent pas dans la fenêtre visible du plan, on accélère
      légèrement (atempo <= 1,18 : inaudible) puis on remonte le bloc dans la transition ;
    - chaque réplique reçoit un début et une fin absolus, utilisés par le mixage
      et par les sous-titres : la synchronisation est donc garantie avec le son.
    """
    max_speed = float(sub_cfg.get("max_tempo", 1.25))
    gap = float(sub_cfg.get("line_gap", 0.16))
    for sc, (w0, w1) in zip(scenes, visible_windows(scenes)):
        if not sc.lines:
            continue
        durs = []
        for ln in sc.lines:
            d = ln["dur"]
            if not d and ln["file"] and os.path.exists(ln["file"]):
                d = probe(ln["file"]).get("duration", 0.0)
            if not d:
                d = max(0.9, len(ln["text"].split()) / 2.6)
            durs.append(d)
        window = max(w1 - w0, 0.5)
        needed = sum(durs) + gap * (len(durs) - 1)
        tempo = min(max_speed, max(1.0, needed / window))
        scaled = [d / tempo for d in durs]
        block = sum(scaled) + gap * (len(scaled) - 1)
        start = w0 + 0.04 if block <= window else max(w0 - 0.14, w0 + 0.04 - (block - window))
        t = start
        for ln, d, orig in zip(sc.lines, scaled, durs):
            if tempo >= max_speed and sum(scaled) + gap * (len(scaled) - 1) > window:
                besoin = round(sum(durs) + gap * (len(durs) - 1) + 0.29, 2)
                DIALOGUE_WARNINGS.append(
                    f"plan {sc.index} : la réplique de {ln['who'] or 'voix'} ne tient pas "
                    f"dans {window:.2f}s. Passez la durée du plan à {besoin:.2f}s "
                    f"ou raccourcissez la réplique de "
                    f"{max(1, round((sum(durs) + gap * (len(durs) - 1) - window) * 2.6))} mot(s).")
            sc.lines_planned.append({**ln, "start": round(t, 3), "end": round(t + d, 3),
                                     "tempo": round(orig / d, 4) if d else 1.0})
            t += d + gap


# ----------------------------------------------------------------------------
# Vidéo : préparation du cadre + mouvement
# ----------------------------------------------------------------------------
def motion_expr(motion: str) -> tuple[float, float, float, float]:
    return MOTIONS[motion]


# Sur les images horizontales placées dans un cadre vertical, le panoramique ferait
# sortir le sujet du cadre : on conserve une respiration par zoom uniquement.
COMPOSITE_MOTION = {
    "pan_right": "zoom_in", "pan_left": "zoom_out", "tilt_up": "push_soft",
    "tilt_down": "pull_soft", "dolly_diag": "zoom_in", "dolly_diag_rev": "zoom_out",
}


def frame_chain(scene: Scene, fmt: Format) -> tuple[str, bool, str]:
    """
    Chaîne de filtres d'un plan : cadrage + mouvement.
    Renvoie (graphe, est_complexe, label_sortie).
    """
    info = probe(scene.image)
    iw, ih = info.get("w", 1080), info.get("h", 1920)
    src_aspect = iw / max(ih, 1)
    tgt_aspect = fmt.w / fmt.h
    ss = 1.5  # suréchantillonnage : évite le crénelage pendant le mouvement
    W, H = int(fmt.w * ss) // 2 * 2, int(fmt.h * ss) // 2 * 2

    motion = scene.motion_resolved
    composed = src_aspect > 1.15 and tgt_aspect < 1.0
    if composed:
        motion = COMPOSITE_MOTION.get(motion, motion)
    z0, z1, fx, fy = motion_expr(motion)
    dur = max(scene.dur, 0.2)
    zexpr = f"({z0}+({z1 - z0})*min(t/{dur:.4f},1))"
    xexpr = f"(iw-iw/{zexpr})*({fx})"      # espace de pan = (iw - iw/zoom)
    yexpr = f"(ih-ih/{zexpr})*({fy})"

    tail = (f"crop=w='iw/{zexpr}':h='ih/{zexpr}':x='{xexpr}':y='{yexpr}',"
            f"scale={fmt.w}:{fmt.h}:flags=lanczos,setsar=1,fps={FPS},format=yuv420p")

    if composed:
        # Image horizontale dans un cadre vertical : fond flouté + sujet entier, jamais étiré
        fg_w = int(W * 0.90) // 2 * 2
        graph = (
            f"split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={W}:{H},gblur=sigma={int(26 * ss)}:steps=2,"
            f"eq=brightness=-0.06:saturation=1.06[bgb];"
            f"[fg]scale={fg_w}:-2:flags=lanczos[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2:format=auto[comp];"
            f"[comp]{tail}[vout]"
        )
        return graph, True, "[vout]"
    graph = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={W}:{H}," + tail)
    return graph, False, ""


def render_scene(scene: Scene, fmt: Format, out: str) -> None:
    graph, complex_, label = frame_chain(scene, fmt)
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", str(FPS), "-t", f"{scene.dur:.3f}", "-i", scene.image]
    if complex_:
        cmd += ["-filter_complex", graph, "-map", label]
    else:
        cmd += ["-vf", graph]
    cmd += ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), out]
    run(cmd)


def assemble(scenes: list[Scene], paths: list[str], fmt: Format, out: str) -> float:
    """Assemble les plans avec les transitions (xfade) et renvoie la durée réelle."""
    if len(scenes) == 1:
        shutil.copy(paths[0], out)
        return scenes[0].dur
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    for p in paths:
        cmd += ["-i", p]
    # Normalisation de chaque plan : même base de temps, même cadence (exigé par xfade)
    parts = [f"[{i}:v]fps={FPS},settb=AVTB,format=yuv420p[s{i}]" for i in range(len(scenes))]
    prev = "[s0]"
    offset = scenes[0].dur
    for i in range(1, len(scenes)):
        tr = scenes[i].transition
        d = TRANSITIONS.get(tr, 0.0)
        label = f"[v{i}]"
        if d <= 0.0:
            parts.append(f"{prev}[s{i}]concat=n=2:v=1:a=0{label}")
        else:
            typ = "fade" if tr in ("cut", "dissolve") else tr
            off = offset - d
            parts.append(f"{prev}[s{i}]xfade=transition={typ}:duration={d}:offset={off:.3f}{label}")
        prev = label
        offset = offset + scenes[i].dur - d
    filter_complex = ";".join(parts)
    cmd += ["-filter_complex", filter_complex, "-map", prev,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), out]
    run(cmd)
    return offset


# ----------------------------------------------------------------------------
# Sous-titres et textes incrustés (ASS via libass)
# ----------------------------------------------------------------------------
def chunk_words(text: str, max_words: int = 4) -> list[list[str]]:
    """Découpe en groupes de mots sans jamais couper un mot."""
    words = text.split()
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (len(" ".join(cur)) > 26 and len(cur) >= 2):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    # évite les paquets d'un seul mot en fin de phrase (flash trop court à l'écran)
    if len(out) > 1 and len(out[-1]) == 1:
        while len(out[-1]) < 2 and len(out[-2]) > 2:
            out[-1].insert(0, out[-2].pop())
    return out or [[]]


def visible_windows(scenes: list[Scene]) -> list[tuple[float, float]]:
    """Fenêtre réellement à l'écran de chaque plan (transitions retirées de part et d'autre)."""
    wins = []
    for i, sc in enumerate(scenes):
        d_in = TRANSITIONS.get(sc.transition, 0.0) if i > 0 else 0.0
        d_out = TRANSITIONS.get(scenes[i + 1].transition, 0.0) if i + 1 < len(scenes) else 0.0
        wins.append((sc.start + d_in / 2, sc.start + sc.dur - d_out / 2))
    return wins


def cue_timings(chunks: list[list[str]], start: float, end: float,
                words_per_sec: float = 2.6) -> list[tuple[float, float]]:
    """
    Répartit les sous-titres dans la fenêtre visible du plan.
    Contraintes : vitesse de lecture naturelle, minimum 0,7 s, jamais au-delà de la fenêtre.
    """
    window = max(end - start, 0.4)
    start = start + 0.05
    end = max(end, start + 0.4)
    total_words = sum(len(c) for c in chunks) or 1
    ideal = [max(0.7, min(2.6, max(len(c) * 0.42, 0.7))) for c in chunks]
    scale = min(1.0, window / sum(ideal)) if sum(ideal) > 0 else 1.0
    times, t = [], start
    for c, d in zip(chunks, ideal):
        d *= scale
        a = min(t, end - 0.35)
        times.append((a, min(a + d, end)))
        t = a + d
    return times


def fit_size(text: str, font_px: int, max_width: int, min_ratio: float = 0.58) -> int:
    """Réduit la taille d'un texte incrusté pour qu'il tienne dans la largeur utile."""
    est = 0.60 * font_px * len(text)          # approximation Montserrat/Inter extra-bold
    if est <= max_width:
        return font_px
    return max(int(font_px * max_width / est), int(font_px * min_ratio))


def ass_time(t: float) -> str:
    t = max(t, 0.0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build_ass(tl: dict, fmt: Format, path: str) -> dict:
    """Écrit le fichier ASS (textes hook/CTA + sous-titres) et renvoie le rapport texte."""
    brand = tl["meta"].get("brand", {})
    cast = tl.get("cast", {})
    accent = brand.get("accent", "#FFC300")
    white = "#FFFFFF"
    sub_cfg = tl["subtitles"]
    f_title = sub_cfg.get("font", "Montserrat")
    f_body = sub_cfg.get("body_font", "Inter")
    base = fmt.h / 1920  # échelle typographique relative

    def size(px: int) -> int:
        return max(18, int(px * base))

    styles = [
        ("Hook", f_title, size(122), hex_to_ass(white), hex_to_ass(accent), 8),
        ("Kicker", f_title, size(86), hex_to_ass(accent), hex_to_ass(white), 7),
        ("Body", f_body, size(74), hex_to_ass(white), hex_to_ass(accent), 6),
        ("Sub", f_body, size(78), hex_to_ass(white), hex_to_ass(accent), 7),
        ("CTA", f_title, size(94), hex_to_ass(white), hex_to_ass(accent), 8),
        ("Speaker", f_title, size(50), hex_to_ass(accent), hex_to_ass(white), 6),
    ]
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {fmt.w}", f"PlayResY: {fmt.h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    for name, font, fsize, prim, sec, outline in styles:
        # contour épais + ombre portée : lisible sur n'importe quelle image, sans bandeau opaque
        box = "&H96000000"
        head.append(
            f"Style: {name},{font},{fsize},{prim},{sec},{hex_to_ass('#0E1218')},{box},"
            f"-1,0,0,0,100,100,0,0,1,{outline + 1},3,5,{fmt.side},{fmt.side},10,1")
    head += ["", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    report = {"cues": [], "first_text_at": None, "has_cta": False}
    pending: list[dict] = []   # éléments à afficher, dé-chevauvrés avant écriture

    def add(style: str, start: float, end: float, text: str, y: int,
            emph: list[str] | None = None, fade: float = 0.12, is_cue: bool = False,
            color: str = "", who: str = "", x: int | None = None,
            size: int | None = None) -> None:
        start, end = max(start, 0.0), min(end, tl["total"])
        if end <= start + 0.05 or not text.strip():
            return
        pending.append({"style": style, "start": start, "end": end, "text": text, "y": y,
                        "emph": emph or [], "fade": fade, "cue": is_cue, "scene": 0,
                        "color": color, "who": who, "x": x, "size": size})

    # Ordre d'apparition des personnages : sert à placer leur badge d'un côté puis de l'autre
    order: list[str] = []
    for sc in tl["scenes"]:
        for ln in sc.lines_planned:
            if ln["who"] and ln["who"] not in order:
                order.append(ln["who"])
    sides = {who: (-1 if i % 2 == 0 else 1) for i, who in enumerate(order)}
    # Fin du badge bornée au début de la réplique suivante (pas de superposition)
    flat = sorted([ln for sc in tl["scenes"] for ln in sc.lines_planned],
                  key=lambda l: l["start"])
    nxt_start = {id(ln): (flat[i + 1]["start"] if i + 1 < len(flat) else float("inf"))
                 for i, ln in enumerate(flat)}

    windows = visible_windows(tl["scenes"])
    key = [k.lower() for k in tl["meta"].get("keywords", [])]
    for sc, (w0, w1) in zip(tl["scenes"], windows):
        # 1. Textes incrustés (hook, corps, CTA) — affichés pendant la fenêtre visible du plan
        if sc.text:
            room = fmt.w - 2 * fmt.side
            if sc.text_style == "hook":
                fs = fit_size(sc.text.upper(), size(122), room)
                add("Hook", w0 + 0.08, w1, sc.text.upper(), fmt.top + int(fmt.h * 0.22),
                    sc.emph, size=fs)
            elif sc.text_style == "cta":
                fs = fit_size(sc.text, size(94), room)
                add("CTA", w0 + 0.08, w1, sc.text, fmt.h - fmt.bottom - int(fmt.h * 0.05),
                    sc.emph, size=fs)
                report["has_cta"] = True
            elif sc.text_style == "kicker":
                fs = fit_size(sc.text.upper(), size(86), room)
                add("Kicker", w0 + 0.08, w1, sc.text.upper(), fmt.top + int(fmt.h * 0.10),
                    sc.emph, size=fs)
            else:
                fs = fit_size(sc.text, size(74), room)
                add("Body", w0 + 0.08, w1, sc.text, fmt.top + int(fmt.h * 0.30), sc.emph, size=fs)

        # Position des sous-titres de ce plan : au-dessus du CTA s'il y en a un
        sub_y = int(fmt.h * fmt.sub_y)
        if sc.text and sc.text_style == "cta":
            sub_y = min(sub_y, fmt.h - fmt.bottom - int(fmt.h * 0.05) - int(fmt.h * 0.085))
        sub_y = max(sub_y, fmt.top + int(fmt.h * 0.34))

        # 2a. Format podcast / fiction : une réplique = un badge de personnage + des sous-titres
        if sub_cfg.get("enabled", True) and sc.lines_planned:
            show_who = bool(sub_cfg.get("show_speaker", True))
            tag_y = sub_y - int(fmt.h * 0.058)
            for ln in sc.lines_planned:
                if not ln["text"]:
                    continue
                chunk = chunk_words(ln["text"], max_words=int(sub_cfg.get("max_words", 4)))
                spans = cue_timings(chunk, ln["start"], ln["end"])
                if show_who and ln["who"]:
                    side = sides.get(ln["who"], -1)
                    x = int(fmt.w * (0.26 if side < 0 else 0.74))
                    end_tag = min(ln["end"] + 0.08, nxt_start[id(ln)] - 0.02)
                    add("Speaker", ln["start"] - 0.02, end_tag, ln["who"].upper(), tag_y,
                        color=cast.get(ln["who"], {}).get("color", accent), x=x)
                for (a, b), ch in zip(spans, chunk):
                    emph = [w for w in ch if w.strip(".,!?:;»«\"'").lower() in key]
                    add("Sub", a, b, " ".join(ch), sub_y, emph, fade=0.06,
                        is_cue=True, who=ln["who"])
                    pending[-1]["scene"] = sc.index

        # 2b. Voix off continue : sous-titres découpés en groupes de 3 à 5 mots
        elif sub_cfg.get("enabled", True) and sc.vo:
            chunks = chunk_words(sc.vo, max_words=int(sub_cfg.get("max_words", 4)))
            onscreen = re.sub(r"[^a-z0-9 ]", "", sc.text.lower()) if sc.text else ""
            for (a, b), ch in zip(cue_timings(chunks, w0 + 0.04, w1), chunks):
                shown = " ".join(ch).lower()
                if onscreen and shown and shown in onscreen:
                    continue  # le texte est déjà à l'écran : inutile de le doubler
                emph = [w for w in ch if w.strip(".,!?:;»«\"'").lower() in key]
                add("Sub", a, b, " ".join(ch), sub_y, emph, fade=0.08, is_cue=True)
                pending[-1]["scene"] = sc.index

    # Signature / handle du compte, sur la toute fin
    handle = tl["meta"].get("handle")
    if handle:
        y = (fmt.top + int(fmt.h * 0.045) if report["has_cta"]
             else fmt.h - fmt.bottom - int(fmt.h * 0.012))
        add("Kicker", tl["total"] - 1.6, tl["total"], handle, y)

    # Dé-chevauchement global des sous-titres : on raccourcit l'affichage précédent,
    # et si c'est impossible on retarde légèrement l'affichage suivant.
    cues = sorted([p for p in pending if p["cue"]], key=lambda p: p["start"])
    for prev, nxt in zip(cues, cues[1:]):
        if nxt["start"] < prev["end"]:
            prev["end"] = max(prev["start"] + 0.35, nxt["start"] - 0.03)
        if nxt["start"] < prev["end"]:
            nxt["start"] = prev["end"]
        if nxt["end"] <= nxt["start"] + 0.2:
            nxt["end"] = min(nxt["start"] + 0.6, tl["total"])

    events: list[str] = []
    for p in sorted(pending, key=lambda p: p["start"]):
        body = p["text"]
        if p.get("size"):
            body = f"{{\\fs{p['size']}}}" + body
        if p.get("color"):
            body = "{\\c" + hex_to_ass(p["color"]) + "}" + body
        for w in p["emph"]:
            body = re.sub(rf"(?i)(\b{re.escape(w)}\b)",
                          r"{\\c" + hex_to_ass(accent) + r"}\1{\\c" + hex_to_ass(white) + "}", body)
        events.append(
            f"Dialogue: 0,{ass_time(p['start'])},{ass_time(p['end'])},{p['style']},,0,0,0,,"
            f"{{\\an5\\pos({p['x'] if p.get('x') is not None else fmt.w // 2},{p['y']})"
            f"\\fad({int(p['fade']*1000)},{int(p['fade']*1000)})}}{body}")
        if p["cue"]:
            entry = {"start": round(p["start"], 2), "end": round(p["end"], 2),
                     "words": len(p["text"].split()), "text": p["text"], "scene": p["scene"]}
            if p.get("who"):
                entry["who"] = p["who"]
            report["cues"].append(entry)
        if p["cue"] and report["first_text_at"] is None:
            report["first_text_at"] = round(p["start"], 2)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head + events) + "\n")
    return report


def write_srt(report: dict, path: str) -> None:
    def ts(t: float) -> str:
        h, m, s, ms = int(t // 3600), int(t % 3600 // 60), int(t % 60), int(t % 1 * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, c in enumerate(report["cues"], start=1):
        body = f"{c['who']} : {c['text']}" if c.get("who") else c["text"]
        lines += [str(i), f"{ts(c['start'])} --> {ts(c['end'])}", body, ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ----------------------------------------------------------------------------
# Audio : voix (voix off et/ou répliques) + musique duckée + SFX, norme -14 LUFS
# ----------------------------------------------------------------------------
def sfx_path(name: str) -> str:
    return os.path.join(ROOT, "tools", "assets", f"sfx_{name}.wav")


def measure_loudness(path: str) -> dict:
    """Mesure EBU R128 (intégrée, crête vraie, plage dynamique)."""
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", path,
                           "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True)
    out = proc.stderr
    def grab(pattern: str) -> float | None:
        found = re.findall(pattern, out)
        return float(found[-1]) if found else None
    return {"i": grab(r"I:\s*(-?\d+\.\d+)\s*LUFS"),
            "lra": grab(r"LRA:\s*(-?\d+\.\d+)\s*LU"),
            "tp": grab(r"Peak:\s*(-?\d+\.\d+)\s*dBFS")}


def normalize_audio(src: str, dst: str, total: float, target: float = -14.0,
                    ceiling_db: float = -1.6) -> None:
    """
    Normalisation de diffusion par gain linéaire mesuré (EBU R128).

    Un gain linéaire déplace la loudness intégrée d'autant : on atteint donc la cible
    -14 LUFS exactement, sans les surprises du mode dynamique. Le gain est plafonné
    par la crête vraie mesurée pour ne jamais saturer : mieux vaut 0,5 LU de moins
    qu'un son écrasé.
    """
    stats = measure_loudness(src)
    i, tp = stats["i"], stats["tp"]
    if i is None or i <= -70:      # quasi silence : rien à normaliser
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src,
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", dst])
        return
    gain = target - i
    if tp is not None:
        gain = min(gain, ceiling_db - tp)          # plafond de crête
    gain = max(min(gain, 24.0), -24.0)
    chain = (f"volume={gain:.2f}dB,"
             f"alimiter=limit={10 ** (ceiling_db / 20):.4f}:level=disabled")
    run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-af", chain, "-t", f"{total:.3f}",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", dst])


def mix_audio(tl: dict, out: str, workdir: str) -> None:
    """
    Mixage : sources voix (voix off continue et/ou répliques de personnages), musique
    duckée sous la voix, effets sonores aux coupes, puis normalisation -14 LUFS.
    """
    audio = tl["audio"]
    total = tl["total"]
    music = tl["music"] if tl["music"] and os.path.exists(tl["music"]) else ""

    # Sources voix : (chemin, départ absolu, tempo, gain en dB)
    voices: list[tuple[str, float, float, float]] = []
    if tl["voiceover"] and os.path.exists(tl["voiceover"]):
        voices.append((tl["voiceover"], 0.0, 1.0, 0.0))
    for sc in tl["scenes"]:
        for ln in sc.lines_planned:
            if ln["file"] and os.path.exists(ln["file"]):
                voices.append((ln["file"], ln["start"], ln.get("tempo", 1.0),
                               ln.get("gain_db", 0.0)))

    sfx_events = [(s.start + 0.02, s.sfx) for s in tl["scenes"] if s.sfx and s.sfx != "none"]
    sfx_events = [(t, n) for t, n in sfx_events if os.path.exists(sfx_path(n))]

    inputs: list[str] = []
    voice_idx: list[int] = []
    n_in = 0                      # numéro d'entrée FFmpeg (≠ position dans la liste)
    for path, _, _, _ in voices:
        voice_idx.append(n_in)
        n_in += 1
        inputs += ["-i", path]
    music_idx = None
    if music:
        music_idx = n_in
        n_in += 1
        inputs += ["-stream_loop", "-1", "-i", music]
    sfx_idx: dict[int, int] = {}
    for k, (_, name) in enumerate(sfx_events):
        sfx_idx[k] = n_in
        n_in += 1
        inputs += ["-i", sfx_path(name)]

    if not inputs:
        # Piste silencieuse : évite un fichier vidéo sans audio
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}",
             "-c:a", "aac", "-b:a", "192k", out])
        return

    parts: list[str] = []
    voice_bus = None
    for n, ((path, t0, tempo, gain), idx) in enumerate(zip(voices, voice_idx)):
        chain = f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo"
        if abs(tempo - 1.0) > 0.01:
            # accélération imperceptible pour caler une réplique sur son plan
            t = tempo
            while t > 2.0:
                chain += ",atempo=2.0"
                t /= 2.0
            chain += f",atempo={t:.4f}"
        chain += ",dynaudnorm=f=200:g=7:p=0.92:m=4"    # homogénéise les niveaux entre voix
        if t0 > 0.02:
            chain += f",adelay={int(t0 * 1000)}|{int(t0 * 1000)}"
        if gain:
            chain += f",volume={gain:.1f}dB"
        chain += f",apad,atrim=0:{total:.3f},asetpts=N/SR/TB[vs{n}]"
        parts.append(chain)
    if voices:
        labels = "".join(f"[vs{n}]" for n in range(len(voices)))
        if len(voices) == 1:
            parts.append(f"{labels}anull[voice]")
        else:
            parts.append(f"{labels}amix=inputs={len(voices)}:duration=longest:normalize=0[voice]")
        voice_bus = "[voice]"

    bed = None
    if music_idx is not None:
        gain = audio.get("music_gain_db", -13.5)
        parts.append(f"[{music_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"atrim=0:{total:.3f},asetpts=N/SR/TB,volume={gain}dB,"
                     f"afade=t=in:st=0:d=0.6,afade=t=out:st={max(total - 1.2, 0):.2f}:d=1.2[music]")
        if voice_bus:
            # Ducking : la musique descend d'environ 18 dB sous la voix
            parts.append(f"[music]asplit=2[mA][mB];"
                         f"{voice_bus}asplit=2[ky][vkeep];"
                         f"[mB][ky]sidechaincompress=threshold=0.035:ratio=12:attack=25:"
                         f"release=450:makeup=1:level_sc=1.2[ducked];"
                         f"[vkeep][mA][ducked]amix=inputs=3:duration=longest:normalize=0[mixm]")
            bed = "[mixm]"
        else:
            bed = "[music]"

    mix_inputs = [bed] if bed else (["[voice]"] if voices else [])
    for k, (t0, _) in enumerate(sfx_events):
        delay = int(t0 * 1000)
        parts.append(f"[{sfx_idx[k]}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"adelay={delay}|{delay},volume=-9dB[sfx{k}]")
        mix_inputs.append(f"[sfx{k}]")

    joined = "".join(mix_inputs)
    if len(mix_inputs) == 1:
        parts.append(f"{joined}anull[mixed]")
    else:
        parts.append(f"{joined}amix=inputs={len(mix_inputs)}:duration=longest:normalize=0,"
                     f"alimiter=limit=0.95:level=disabled[mixed]")
    raw = os.path.join(workdir, "mix_raw.m4a")
    run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"] + inputs + [
        "-filter_complex", ";".join(parts), "-map", "[mixed]", "-t", f"{total:.3f}",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000", raw])
    normalize_audio(raw, out, total, target=audio.get("target_lufs", -14.0))


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------
FPS = 30


def render(tl_path: str, aspects: list[str], outdir: str, dry: bool = False) -> None:
    tl = load_timeline(tl_path)
    scenes = tl["scenes"]
    os.makedirs(outdir, exist_ok=True)
    work = os.path.join(outdir, "_work")
    os.makedirs(work, exist_ok=True)
    name = slugify(tl["meta"].get("title", "video"))

    print(f"▸ {len(scenes)} plans · durée montée {tl['total']:.2f} s · "
          f"{tl['total']/len(scenes):.2f} s/plan")
    for w in DIALOGUE_WARNINGS:
        print(f"   ⚠ {w}")
    for sc in scenes:
        print(f"   plan {sc.index:>2} | {sc.dur:4.2f}s | {os.path.basename(sc.image):<22} "
              f"| {sc.motion_resolved:<14} | {sc.transition:<10} | {sc.text or sc.vo[:38]}")

    if dry:
        print("(dry-run : aucun rendu)")
        return

    # Audio (une seule fois, partagé entre tous les formats)
    audio_mix = os.path.join(work, "mix.m4a")
    print("▸ Mixage audio (voix off + musique duckée + SFX, -14 LUFS)")
    mix_audio(tl, audio_mix, work)

    ff = ffmpeg()
    for aspect in aspects:
        fmt = FORMATS[aspect]
        print(f"▸ Format {aspect} ({fmt.w}x{fmt.h})")
        paths = []
        for sc in scenes:
            p = os.path.join(work, f"s{sc.index}_{aspect.replace(':', 'x')}.mp4")
            render_scene(sc, fmt, p)
            paths.append(p)
        master = os.path.join(work, f"master_{aspect.replace(':', 'x')}.mp4")
        assemble(scenes, paths, fmt, master)

        ass = os.path.join(work, f"{name}_{aspect.replace(':', 'x')}.ass")
        report = build_ass(tl, fmt, ass)
        write_srt(report, os.path.join(outdir, f"{name}_{aspect.replace(':', 'x')}.srt"))

        final = os.path.join(outdir, f"{name}_{aspect.replace(':', 'x')}.mp4")
        run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", master, "-i", audio_mix,
             "-vf", f"subtitles={ass}:fontsdir={FONTS_DIR}",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", "-shortest", final])
        rp = dict(report)
        rp.update({"warnings": DIALOGUE_WARNINGS, "aspect": aspect, "resolution": f"{fmt.w}x{fmt.h}",
                   "duration": tl["total"], "file": final,
                   "safe_zone": {"top": fmt.top, "bottom": fmt.bottom, "side": fmt.side},
                   "scenes": [{"index": s.index, "start": round(s.start, 3), "dur": s.dur,
                               "lines": [{"who": l["who"], "start": l["start"], "end": l["end"],
                                          "tempo": l["tempo"], "text": l["text"]}
                                         for l in s.lines_planned],
                               "image": os.path.basename(s.image),
                               "motion": s.motion_resolved, "transition": s.transition,
                               "text_style": s.text_style, "has_text": bool(s.text),
                               "has_vo": bool(s.vo)} for s in scenes],
                   "music_gain_db": tl["audio"].get("music_gain_db", -13.5)})
        with open(os.path.join(outdir, f"{name}_{aspect.replace(':', 'x')}_report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(rp, fh, ensure_ascii=False, indent=2)
        print(f"   ✔ {os.path.basename(final)}")
    print("▸ Terminé. Vérifiez avec : python3 tools/qc.py " + outdir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Moteur de montage elimarket")
    ap.add_argument("timeline")
    ap.add_argument("--aspects", default="9:16",
                    help="formats à produire, séparés par des virgules (9:16,4:5,1:1,16:9)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true", help="affiche le découpage sans rendre")
    args = ap.parse_args()
    aspects = [a.strip() for a in args.aspects.split(",") if a.strip()]
    for a in aspects:
        if a not in FORMATS:
            sys.exit(f"Format inconnu : {a} (choix : {', '.join(FORMATS)})")
    outdir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.timeline)), "..", "output")
    render(args.timeline, aspects, os.path.abspath(outdir), args.dry_run)


if __name__ == "__main__":
    main()
