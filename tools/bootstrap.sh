#!/usr/bin/env bash
# Bootstrap de la chaîne de montage — elimarket / Arena
# Installe : FFmpeg (statique, via PyPI car apt est bloqué dans le sandbox),
# MoviePy + Pillow + numpy, et convertit les polices woff2 -> ttf dans assets/fonts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

echo "== 1/4 Dépendances Python =="
pip3 install --break-system-packages --quiet moviepy pillow numpy imageio-ffmpeg fonttools brotli \
  || pip3 install --quiet moviepy pillow numpy imageio-ffmpeg fonttools brotli

echo "== 2/4 FFmpeg =="
FF="$(python3 -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')"
mkdir -p "$HOME/.local/bin"
ln -sf "$FF" "$HOME/.local/bin/ffmpeg"
ln -sf "$FF" "$HOME/.local/bin/ffprobe"   # le binaire statique gère aussi la sonde
"$FF" -version | head -1

echo "== 3/4 Polices =="
if ! ls "$ROOT"/assets/fonts/*.ttf >/dev/null 2>&1; then
  TMP="$(mktemp -d)"
  (cd "$TMP" && npm pack @fontsource/montserrat @fontsource/inter --silent >/dev/null 2>&1)
  mkdir -p "$TMP/ext"
  for t in "$TMP"/*.tgz; do tar xzf "$t" -C "$TMP/ext"; done
  python3 - "$TMP" "$ROOT/assets/fonts" <<'PY'
import glob, os, sys
from fontTools.ttLib import TTFont
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
want = {"montserrat": [500, 700, 800, 900], "inter": [400, 600, 700]}
for f in sorted(glob.glob(os.path.join(src, "ext/package/files/*.woff2"))):
    fam, sub, w, style = os.path.basename(f)[:-6].split("-")[:4]
    if fam not in want or sub != "latin" or style != "normal" or int(w) not in want[fam]:
        continue
    ft = TTFont(f); ft.flavor = None
    ft.save(os.path.join(out, f"{fam.capitalize()}-{w}.ttf"))
PY
  rm -rf "$TMP"
fi
ls -1 "$ROOT"/assets/fonts/*.ttf | sed "s|$ROOT/||"

echo "== 4/4 Effets sonores =="
python3 "$ROOT/tools/make_sfx.py"

echo "== Prêt =="
echo "Commande type : python3 tools/render.py project/timeline.json --aspects 9:16"
