# elimarket

Elimarket.africa — Marketplace de confiance.

Ce dépôt contient la chaîne de production vidéo du projet : à partir des images et du scénario,
elle génère des vidéos prêtes à publier sur TikTok, Facebook (Reels/feed) et YouTube.

## Démarrage rapide

```bash
bash tools/bootstrap.sh                     # FFmpeg + Python + polices (une seule fois)
python3 tools/selftest.py                   # auto-test de la chaîne
python3 tools/render.py project/timeline.json --aspects 9:16
python3 tools/qc.py project/output --frames # contrôle qualité avant publication
```

## Documentation

- [`docs/GUIDE.md`](docs/GUIDE.md) — méthode de montage, schéma de la timeline, normes par plateforme
- [`docs/BRIEF.md`](docs/BRIEF.md) — informations à fournir pour lancer une vidéo
- [`project/timeline.example.json`](project/timeline.example.json) — exemple de découpage commenté

## Points clés

- Aucun service externe : FFmpeg et Python font tout, en local.
- Images jamais déformées : verticales en plein cadre, horizontales recomposées sur fond flouté.
- Sous-titres incrustés (3 à 5 mots, mot-clé surligné) dans la zone sûre de chaque plateforme.
- Musique et effets sonores générés par le dépôt : libres de droits par construction.
- Norme de diffusion : −14 LUFS, crête sous −1 dBTP, voix toujours au-dessus de la musique.

Licence : MIT (voir [`LICENSE`](LICENSE)).
