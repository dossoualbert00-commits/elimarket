Polices du montage elimarket
============================

Montserrat (500/700/800/900) : titres, hooks, appels à l'action.
Inter (400/600/700)          : sous-titres, textes secondaires.

Licence : SIL Open Font License 1.1 — usage commercial et incrustation vidéo autorisés.
  https://github.com/JulietaUla/Montserrat/blob/master/OFL.txt
  https://github.com/rsms/inter/blob/master/LICENSE.txt

Ces fichiers sont les sous-ensembles latins (caractères français, accents, chiffres,
ponctuation), convertis de WOFF2 en TTF car libass (FFmpeg) ne lit pas le WOFF2.

Pour ajouter une graisse ou une langue : modifier la liste `want` dans tools/bootstrap.sh,
puis relancer `bash tools/bootstrap.sh` après avoir supprimé les .ttf du dossier.
