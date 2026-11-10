#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recorta el fondo de los frames del sticker (IA rembg, modelo humano)
y arma el .webm final con transparencia (formato sticker de Telegram)."""

import subprocess
import sys
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

FFMPEG = "C:/Users/Intel/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe"
AQUI = Path(__file__).resolve().parent / "sticker"
FRAMES = AQUI / "frames"
CUT = AQUI / "cut"
SALIDA = AQUI / "sticker.webm"
MAX_BYTES = 256 * 1024


def correr(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-1500:])
        sys.exit("Falló ffmpeg")


def main():
    CUT.mkdir(exist_ok=True)
    frames = sorted(FRAMES.glob("f_*.png"))
    if not frames:
        sys.exit("No hay frames en {}".format(FRAMES))

    print("Cargando modelo de recorte (la primera vez baja ~170 MB)...", flush=True)
    session = new_session("u2net_human_seg")

    for i, f in enumerate(frames, 1):
        recortado = remove(Image.open(f), session=session)
        recortado.save(CUT / f.name)
        print("frame {}/{}".format(i, len(frames)), flush=True)

    print("Recodificando a WebM con transparencia...", flush=True)
    temp = AQUI / "temporal_alpha.mkv"
    correr(
        [
            FFMPEG, "-y", "-framerate", "30", "-i", str(CUT / "f_%03d.png"),
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
            "-crf", "40", "-an", str(temp),
        ]
    )
    for crf in (40, 44, 48, 52):
        correr(
            [
                FFMPEG, "-y", "-i", str(temp),
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
                "-crf", str(crf), "-an", str(SALIDA),
            ]
        )
        peso = SALIDA.stat().st_size
        print("crf {}: {:.0f} KB".format(crf, peso / 1024), flush=True)
        if peso <= MAX_BYTES:
            print("LISTO: {} ({:.0f} KB, con transparencia)".format(SALIDA, peso / 1024), flush=True)
            return 0
    sys.exit("No entró en 256 KB")


if __name__ == "__main__":
    sys.exit(main())
