# Guide de montage — elimarket

Chaîne de production vidéo locale : images + scénario → vidéo prête à publier (TikTok, Reels/Facebook, YouTube), sans dépendance externe, sans question de droits musicaux.

## 1. Arborescence

```
project/
  images/            # les images fournies (jamais modifiées, jamais étirées au montage)
  audio/             # voix off enregistrée (optionnel) + lit musical généré
  timeline.json      # le découpage validé (voir timeline.example.json)
  output/            # rendus finaux + .srt + rapport de contrôle (non versionnés)
tools/
  bootstrap.sh       # installe FFmpeg, MoviePy, Pillow, polices (à lancer une fois)
  render.py          # moteur : timeline JSON → vidéo(s)
  qc.py              # contrôle qualité avant livraison
  make_music.py      # lit musical libre de droits (synthèse locale)
  make_sfx.py        # whoosh / riser / impact / pop / click (synthèse locale)
  selftest.py        # auto-test complet de la chaîne
assets/fonts/        # Montserrat + Inter (SIL OFL), converties en TTF pour libass
```

## 2. Mise en route

```bash
bash tools/bootstrap.sh          # une seule fois
python3 tools/selftest.py        # vérifie que toute la chaîne fonctionne (≈ 1 min)
```

## 3. Produire une vidéo

```bash
# 1. déposer les images dans project/images/
# 2. écrire le découpage dans project/timeline.json (copier timeline.example.json)
# 3. vérifier le découpage sans rendre
python3 tools/render.py project/timeline.json --dry-run

# 4. rendre une ou plusieurs versions (le cadrage est retravaillé pour chaque format)
python3 tools/render.py project/timeline.json --aspects 9:16,4:5,1:1,16:9

# 5. contrôle qualité (+ vignettes de contrôle par plan)
python3 tools/qc.py project/output --frames
```

Sorties dans `project/output/` : `*_9x16.mp4` (TikTok / Reels / Shorts), `*_4x5.mp4` (feed Facebook), `*_1x1.mp4`, `*_16x9.mp4` (YouTube), un `.srt` par format, et un `_report.json` (plan par plan + minutage des sous-titres).

## 4. Règles de montage appliquées automatiquement

| Règle | Mise en œuvre |
|---|---|
| Hook dans les 2 premières secondes | texte de style `hook` affiché dès 0,08 s |
| Aucun plan statique > 3 s | mouvement imposé (`zoom`, `pan`, `parallaxe`) sur chaque plan |
| Images jamais déformées | verticales en plein cadre ; horizontales sur fond flouté, sujet entier |
| Sous-titres lisibles | 1 à 5 mots par affichage, mot-clé surligné, jamais coupés, jamais en dehors de la zone sûre |
| Zones sûres par plateforme | marges hautes/basses réservées à l'interface (pseudo, boutons, légende) |
| Cohérence | Montserrat (titres) + Inter (sous-titres), un seul style de transition par vidéo |
| Coupes sur le temps fort | transitions alignées sur la grille du lit musical |
| Voix au-dessus de la musique | sidechain : la musique descend d'environ 18 dB sous la voix |
| Niveau de diffusion | voix + musique normalisées à −14 LUFS, crête < −1 dBTP |
| Boucle (TikTok/Shorts) | dernier plan call-to-action qui renvoie au hook du début |

## 5. Correspondance des formats

| Cible | Format | Résolution | Durée | Sous-titres |
|---|---|---|---|---|
| TikTok | `9:16` | 1080×1920 | 15–45 s | obligatoires |
| Facebook Reels | `9:16` | 1080×1920 | 15–60 s | obligatoires |
| Facebook feed | `4:5` | 1080×1350 | 15–60 s | obligatoires |
| YouTube long | `16:9` | 1920×1080 | selon scénario | recommandés |
| YouTube Shorts | `9:16` | 1080×1920 | < 60 s | obligatoires |

Le passage d'un format à l'autre refait le cadrage (recomposition, marges, densité des sous-titres) : ce n'est pas un simple redimensionnement.

## 6. Contrôle qualité (`tools/qc.py`)

Vérifie automatiquement : résolution, durée, cadence, piste audio, hook ≤ 2 s, nombre de mots par sous-titre, chevauchements, trous de sous-titres, dépassement de la fin, plans statiques > 3 s, présence de l'appel à l'action, loudness (−14 LUFS ±1,5), crête vraie, poids du fichier. Un point en échec est corrigé puis revérifié avant livraison.

## 7. Droits

- Les images fournies par le client restent la propriété du client.
- Le lit musical et les effets sonores sont **générés localement** par synthèse : aucun sample tiers, donc aucune revendication de droits possible sur TikTok/YouTube.
- Polices Montserrat et Inter sous licence SIL OFL (usage commercial autorisé).
