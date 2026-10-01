#!/usr/bin/env python3
"""
Génération d'effets sonores libres de droits (synthèse locale, aucune banque externe).
Sortie : tools/assets/sfx_whoosh.wav, sfx_riser.wav, sfx_impact.wav, sfx_pop.wav, sfx_click.wav

  python3 tools/make_sfx.py            # (re)génère tous les effets
"""
from __future__ import annotations

import os
import wave

import numpy as np

SR = 48000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def write_wav(path: str, sig: np.ndarray) -> None:
    sig = np.clip(sig, -1, 1)
    pcm = (sig * 32767).astype("<i2")
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())


def env(n: int, attack: float, decay: float) -> np.ndarray:
    a = max(int(attack * SR), 1)
    d = max(int(decay * SR), 1)
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a)
    tail = np.linspace(1, 0, d) ** 2
    e[a:a + d] = tail[: max(n - a, 0)]
    return e


def whoosh(dur: float = 0.7, up: bool = True) -> np.ndarray:
    """Balayage de bruit filtré : transition rapide."""
    n = int(dur * SR)
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, n + 4096)
    # filtre passe-bande à fréquence glissante (une seule passe vectorisée)
    freqs = np.linspace(400, 5000, n) if up else np.linspace(5000, 400, n)
    alpha = np.clip(2 * np.pi * freqs / SR, 0, 0.9)
    out = np.zeros(n)
    prev = 0.0
    for i in range(0, n, 2048):  # blocs de 2048 : compromis vitesse/continuité
        blk = min(2048, n - i)
        a = alpha[i:i + blk]
        x = noise[i:i + blk]
        y = np.zeros(blk)
        for k in range(blk):
            prev = prev + a[k] * (x[k] - prev)
            y[k] = prev
        out[i:i + blk] = y
    out *= env(n, 0.25, dur - 0.25)
    out /= max(np.max(np.abs(out)), 1e-6)
    return np.stack([out, out], axis=1) * 0.55


def riser(dur: float = 1.6) -> np.ndarray:
    """Montée tonale (tension avant le hook ou l'appel à l'action)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 200 * (2 ** (t / dur * 2.2))
    phase = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(phase) * 0.5 + np.sin(2 * phase) * 0.2
    rng = np.random.default_rng(3)
    air = rng.normal(0, 0.18, n) * np.linspace(0.1, 1, n) ** 2
    sig = (tone + air) * np.linspace(0.05, 1, n) ** 1.5
    sig = sig / max(np.max(np.abs(sig)), 1e-6) * 0.7
    return np.stack([sig, sig], axis=1)


def impact(dur: float = 1.1) -> np.ndarray:
    """Impact grave : appui sur un mot clé ou une coupe forte."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    thump = np.sin(2 * np.pi * (85 * np.exp(-t * 6) + 40) * t) * np.exp(-t * 5.5)
    rng = np.random.default_rng(11)
    crack = rng.normal(0, 1, n) * np.exp(-t * 45) * 0.5
    sig = (thump * 1.1 + crack) * 0.9
    sig /= max(np.max(np.abs(sig)), 1e-6)
    return np.stack([sig, sig], axis=1) * 0.9


def pop(dur: float = 0.28) -> np.ndarray:
    """Petit « pop » pour l'apparition d'un texte."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t * 14) + 220
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 22)
    sig /= max(np.max(np.abs(sig)), 1e-6)
    return np.stack([sig, sig], axis=1) * 0.5


def click(dur: float = 0.12) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(5)
    sig = rng.normal(0, 1, n) * np.exp(-t * 90)
    sig /= max(np.max(np.abs(sig)), 1e-6)
    return np.stack([sig, sig], axis=1) * 0.4


def heartbeat(dur: float = 1.2, bpm: float = 88.0) -> np.ndarray:
    """
    Battement de cœur doux (lub-dub) : utilisé comme pulsation discrète sous un propos
    sensible, ou en nappe rythmique sur un plan de tension. Boucle proprement.
    """
    n = int(dur * SR)
    out = np.zeros(n)
    beat = 60.0 / bpm
    pos = 0.25
    while pos < dur - 0.25:
        for offset, gain, f0 in ((0.0, 1.0, 62.0), (0.26, 0.62, 52.0)):
            start = int((pos + offset) * SR)
            if start >= n:
                break
            d = 0.32
            m = min(int(d * SR), n - start)
            t = np.arange(m) / SR
            thump = (np.sin(2 * np.pi * (f0 * np.exp(-t * 9) + 32) * t)
                     * np.exp(-t * 9.5)) * gain
            out[start:start + m] += thump
        pos += beat
    out = np.convolve(out, np.hanning(180) / np.hanning(180).sum(), mode="same")  # adoucit
    if np.max(np.abs(out)) > 0:
        out /= np.max(np.abs(out))
    return np.stack([out, out], axis=1) * 0.75


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    items = {"whoosh": whoosh(), "riser": riser(), "impact": impact(),
             "pop": pop(), "click": click(), "heartbeat": heartbeat()}
    for k, v in items.items():
        p = os.path.join(OUT, f"sfx_{k}.wav")
        write_wav(p, v)
        print("✔", os.path.relpath(p, os.path.dirname(OUT)))


if __name__ == "__main__":
    main()
