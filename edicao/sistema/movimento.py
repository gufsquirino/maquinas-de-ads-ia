"""Mede o movimento de cada segundo do vídeo e lista os trechos parados.
Uso: python3 movimento.py <video.mp4> [--calmo 0.5] [--minimo 3]

Só precisa de ffmpeg.
"""
import argparse
import re
import subprocess


def movimento(video):
    """Média da diferença entre quadros vizinhos, por segundo do vídeo."""
    saida = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video, "-vf",
         "scale=270:-2,fps=30,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-an", "-f", "null", "-"], capture_output=True, text=True, check=True).stdout
    valores = [float(v) for v in re.findall(r"YAVG=([\d.]+)", saida)]
    return [sum(valores[i:i + 30]) / len(valores[i:i + 30]) for i in range(0, len(valores), 30)]


def trechos_parados(por_segundo, calmo, minimo):
    trechos, ini = [], None
    for i, v in enumerate(por_segundo + [calmo]):
        if v < calmo and ini is None:
            ini = i
        elif v >= calmo and ini is not None:
            if i - ini >= minimo:
                trechos.append((ini, i))
            ini = None
    return trechos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--calmo", type=float, default=0.5, help="abaixo disso o segundo conta como parado")
    ap.add_argument("--minimo", type=int, default=3, help="segundos seguidos para virar aviso")
    a = ap.parse_args()
    seg = movimento(a.video)
    print(f"{len(seg)} s, movimento médio {sum(seg) / len(seg):.2f}")
    parados = trechos_parados(seg, a.calmo, a.minimo)
    print("Trechos parados:", ", ".join(f"{i // 60}:{i % 60:02d}-{f // 60}:{f % 60:02d}" for i, f in parados) or "nenhum")
