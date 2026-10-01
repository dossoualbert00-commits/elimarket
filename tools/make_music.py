#!/usr/bin/env python3
"""
Lit musical libre de droits, généré localement (kick, clap, shaker, basse, nappes).
Aucun sample tiers, aucune question de droits : utilisable tel quel sur TikTok/Reels/YouTube.

  python3 tools/make_music.py --dur 32 --bpm 108 --key A --out project/audio/bed.wav
  python3 tools/make_music.py --dur 32 --style soft --out project/audio/bed_soft.wav
"""
from __future__ import annotations

import argparse
import os
import wave

import numpy as np

SR = 48000


def write_wav(path: str, sig: np.ndarray) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    sig = np.clip(sig, -1, 1)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes((sig * 32767).astype("<i2").tobytes())


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(n - a_n - d_n - r_n, 0)
    return np.concatenate([np.linspace(0, 1, a_n), np.linspace(1, s, d_n),
                           np.full(s_n, s), np.linspace(s, 0, r_n)])[:n]


def kick(dur=0.35) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 26) + 45
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8)
    rng = np.random.default_rng(1)
    click = rng.normal(0, 1, n) * np.exp(-t * 120) * 0.25
    sig = body + click
    return sig / max(np.max(np.abs(sig)), 1e-6)


def clap() -> np.ndarray:
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, n)
    sig = noise * np.exp(-t * 26) + np.roll(noise, 220) * np.exp(-t * 60) * 0.6
    return sig / max(np.max(np.abs(sig)), 1e-6) * 0.8


def shaker() -> np.ndarray:
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(4)
    sig = rng.normal(0, 1, n) * np.exp(-t * 70)
    # accentue l'aigu (filtre différence = passe-haut simple)
    sig = np.diff(np.concatenate([[0], sig]))
    return sig / max(np.max(np.abs(sig)), 1e-6) * 0.35


def tone(freq: float, dur: float, amp: float = 0.3, harm: tuple[float, ...] = (1, 0.35, 0.15),
         a=0.02, d=0.1, s=0.7, r=0.25) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for i, h in enumerate(harm, start=1):
        sig += h * np.sin(2 * np.pi * freq * i * t)
    return sig * adsr(n, a, d, s, r) * amp


def bass(freq: float, dur: float) -> np.ndarray:
    return tone(freq / 2, dur, amp=0.45, harm=(1, 0.5, 0.2, 0.08), a=0.01, d=0.15, s=0.6, r=0.2)


NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8,
        "A": 9, "A#": 10, "B": 11}


def freq_of(name: str, octave: int) -> float:
    semis = NOTE[name] + (octave - 4) * 12 - 9  # A4 = 440
    return 440.0 * (2 ** (semis / 12))


def build(dur: float, bpm: float, root: str, style: str) -> np.ndarray:
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(dur * SR)
    out = np.zeros(n + SR)
    rng = np.random.default_rng(9)

    # Progression mineure i - VI - III - VII (couleur afro-pop / urbaine)
    prog = [(root, 3), (root, 3), (root, 3), (root, 3)]
    degrees = [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")]
    def chord_notes(step: int) -> list[float]:
        off, _ = degrees[step % 4]
        base = NOTE[root] + off
        return [freq_of(root, 3) * (2 ** ((base - NOTE[root]) / 12)) * m
                for m in (2 ** (0 / 12), 2 ** (3 / 12), 2 ** (7 / 12), 2 ** (12 / 12))]

    steps = int(np.ceil(dur / (beat / 2)))
    for i in range(steps):
        t0 = i * beat / 2
        s0 = int(t0 * SR)
        if s0 >= n:
            break
        bar_i = int(t0 // bar)
        step_in_bar = (t0 % bar)

        def add(sig: np.ndarray, gain: float = 1.0) -> None:
            end = min(s0 + len(sig), n)
            out[s0:end] += sig[: end - s0] * gain

        # Batterie
        if i % 4 == 0:
            add(kick(), 0.95)
        if i % 8 == 5:
            add(kick(), 0.7)
        if i % 8 == 4:
            add(clap(), 0.55)
        if style != "soft" and i % 2 == 1:
            add(shaker(), 0.5 * (1 if i % 4 == 3 else 0.7))
        if style == "soft" and i % 4 == 2:
            add(shaker(), 0.25)

        # Basse : fondamentale sur les temps, octave sur les contretemps
        root_f = chord_notes(bar_i)[0] / 2
        if i % 8 == 0:
            add(bass(root_f, beat * 1.6), 0.9)
        elif i % 8 == 6:
            add(bass(root_f * 1.5, beat * 0.6), 0.6)

        # Nappes d'accords (pad) au début de chaque mesure
        if i % 8 == 0:
            notes = chord_notes(bar_i)
            pad = sum(tone(f, bar, amp=0.16, harm=(1, 0.25, 0.1),
                           a=0.35, d=0.4, s=0.75, r=0.6) for f in notes)
            add(pad, 0.5 if style == "soft" else 0.34)

    out = out[:n]
    # Pump : léger ducking à chaque temps fort (respiration « afro »)
    pump = np.ones(n)
    for i in range(int(dur / beat) + 1):
        s0 = int(i * beat * SR)
        seg = min(int(beat * 0.45 * SR), n - s0)
        if seg > 0:
            pump[s0:s0 + seg] *= np.linspace(0.78, 1.0, seg)
    out *= pump
    # Léger écho latéral pour la largeur stéréo
    delay = int(beat / 2 * SR)
    left = out.copy()
    right = out.copy()
    right[delay:] += out[:-delay] * 0.16
    sig = np.stack([left, right], axis=1)
    sig /= max(np.max(np.abs(sig)), 1e-6)
    return sig * 0.85


def main() -> None:
    ap = argparse.ArgumentParser(description="Lit musical libre de droits (synthèse locale)")
    ap.add_argument("--dur", type=float, default=32.0)
    ap.add_argument("--bpm", type=float, default=108.0)
    ap.add_argument("--key", default="A")
    ap.add_argument("--style", default="urban", choices=["urban", "soft"])
    ap.add_argument("--out", default="project/audio/bed.wav")
    a = ap.parse_args()
    write_wav(a.out, build(a.dur, a.bpm, a.key, a.style))
    print(f"✔ {a.out} — {a.dur:.0f}s · {a.bpm:.0f} BPM · tonalité {a.key} mineur")


if __name__ == "__main__":
    main()
