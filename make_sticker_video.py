#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arma el sticker animado (video) para Telegram.

Dos modos:
  - 2 imágenes:  original + editada  -> animación "transformación mágica"
      (la original, un destello brillante, y la editada con corona/bikini)
  - 3 imágenes:  original, corona flotando, editada -> la corona desciende
      y al colocarse cambia la ropa

Convierte todo al formato exacto de sticker de Telegram:
  .webm / VP9 / 512x512 / 30 fps / sin audio / menos de 256 KB / hasta 3s

Uso:
  python make_sticker_video.py original.png editada.png [salida.webm]
  python make_sticker_video.py original.png corona.png editada.png [salida.webm]
"""

import subprocess
import sys
from pathlib import Path

FFMPEG = (
    "C:/Users/Intel/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe"
)
if not Path(FFMPEG).exists():
    FFMPEG = "ffmpeg"

MAX_BYTES = 256 * 1024  # límite de Telegram


def correr(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-1500:])
        sys.exit("Falló ffmpeg")


def normalizar(origen, destino):
    """Lleva cualquier imagen a 512x512 (recorte centrado), como pide Telegram."""
    correr(
        [
            FFMPEG, "-y", "-i", str(origen),
            "-vf",
            "scale=512:512:force_original_aspect_ratio=increase,crop=512:512",
            str(destino),
        ]
    )


def armar_video(rutas, destino):
    """Encadena los frames con fundidos y un destello en la transformación."""
    if len(rutas) == 2:
        # original (1.0s) -> destello+fundido (0.6s) -> editada (0.9s) = 2.5s
        fade = (
            "[0][1]xfade=transition=fade:duration=0.6:offset=1.0,"
            "eq=brightness=0.06:saturation=1.15"  # brillo sutil al transformar
        )
        inputs = []
        for r, t in zip(rutas, ("1.6", "1.5")):
            inputs += ["-loop", "1", "-t", t, "-i", str(r)]
        correr(
            [FFMPEG, "-y"] + inputs
            + ["-filter_complex", fade, "-map", "[v]", "-r", "30",
               "-pix_fmt", "yuv420p", str(destino)]
        )
    else:
        # original -> corona flotando -> corona puesta + bikini
        fade = (
            "[0][1]xfade=transition=fade:duration=0.5:offset=0.8[ab];"
            "[ab][2]xfade=transition=fade:duration=0.5:offset=1.3,"
            "eq=brightness=0.05[v]"
        )
        inputs = []
        for r, t in zip(rutas, ("1.3", "1.0", "1.2")):
            inputs += ["-loop", "1", "-t", t, "-i", str(r)]
        correr(
            [FFMPEG, "-y"] + inputs
            + ["-filter_complex", fade, "-map", "[v]", "-r", "30",
               "-pix_fmt", "yuv420p", str(destino)]
        )


def main():
    args = [Path(p).expanduser() for p in sys.argv[1:]]
    if not 2 <= len(args) <= 3:
        sys.exit(
            "Uso:\n"
            "  python make_sticker_video.py original.png editada.png [salida.webm]\n"
            "  python make_sticker_video.py original.png corona.png editada.png [salida.webm]"
        )
    salida = Path(args[-1]) if args[-1].suffix.lower() == ".webm" else Path("sticker.webm")
    rutas = args if args[-1].suffix.lower() == ".webm" else args
    frames = [r for r in rutas if r.suffix.lower() != ".webm"]
    for p in frames:
        if not p.is_file():
            sys.exit("No encontré: {}".format(p))

    carpeta = Path(__file__).resolve().parent / "sticker"
    carpeta.mkdir(exist_ok=True)
    norm = []
    for i, f in enumerate(frames):
        n = carpeta / "norm_{}.png".format(i)
        normalizar(f, n)
        norm.append(n)
    print("Frames normalizados a 512x512 ({} imágenes).".format(len(norm)))

    temp = carpeta / "temporal.mp4"
    armar_video(norm, temp)
    print("Video de transformación armado. Codificando a WebM/VP9...")

    for crf in (40, 44, 48, 52):
        correr(
            [
                FFMPEG, "-y", "-i", str(temp),
                "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
                "-an", "-r", "30",
                str(salida),
            ]
        )
        peso = salida.stat().st_size
        print("crf {}: {:.0f} KB".format(crf, peso / 1024))
        if peso <= MAX_BYTES:
            print("\nListo: {}".format(salida.resolve()))
            print("Peso: {:.0f} KB (límite 256 KB)".format(peso / 1024))
            return 0
    sys.exit("No pude bajarlo de 256 KB; hay que achicar la duración o el tamaño.")


if __name__ == "__main__":
    sys.exit(main())
