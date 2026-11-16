"""Portão de qualidade de um ad renderizado . Não altera o vídeo.

Uso: python3 conferir.py <final.mp4> [--trab <pasta de trabalho do ad>] [--velocidade 1.12] [--fps 2]

Confere no arquivo exportado:
  1. quadro preto de 0,1 s ou mais;
  2. volume: -15 LUFS (padrão da casa) com margem de 1,5, pico real abaixo de -1 dBTP;
  3. respiros: silêncio de 0,25 s ou mais na voz (lido em <trab>/voz_crua.wav, já na velocidade final);
  4. texto fora da zona segura do Reels/Stories (x 140-940, y 230-1530 em 1080x1920), lido pelo Vision da Apple.
     Só texto de 40 px de altura ou mais (o da edição); a letra miúda das telas do sistema fica de fora;
  5. dado pessoal legível (telefone, @, e-mail, CPF) em qualquer quadro lido;
  6. folha de quadros com a zona segura desenhada, ao lado do vídeo, em <nome>_portao.jpg.
Saída 0 quando passa, 1 quando há o que olhar.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
ZONA = (140, 230, 940, 1530)
# Textos que podem aparecer (ex.: e-mail fictício de uma tela de demonstração), separados por vírgula.
IGNORAR = tuple(t.strip() for t in os.environ.get("EDICAO_IGNORAR", "").split(",") if t.strip())
LEITOR = os.path.expanduser("~/.cache/maquina-edicao/ocr_vision")
PADROES = {
    "telefone": re.compile(r"(\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}"),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "perfil": re.compile(r"(?<![\w])@[a-z0-9_.]{3,}", re.I),
    "cpf": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
}


def rodar(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def preto(video):
    err = rodar(["ffmpeg", "-nostats", "-i", video, "-vf", "blackdetect=d=0.1:pix_th=0.06", "-an", "-f", "null", "-"]).stderr
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err) if float(a) > 0.1]


def volume(video):
    err = rodar(["ffmpeg", "-nostats", "-i", video, "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])
    picos = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    return lufs, float(picos[-1]) if picos else None


def respiros(wav, vel, minimo=0.25):
    with wave.open(wav) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
    if x.ndim > 1:
        x = x.mean(axis=1)
    hop = sr // 100
    n = len(x) // hop
    db = 10 * np.log10(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    chao, forte = np.percentile(db, 10), np.percentile(db, 90)
    th = min(max(chao + 14, forte - 28), forte - 20)
    achados, ini = [], None
    for i, v in enumerate(np.append(db < th, False)):
        if v and ini is None:
            ini = i
        elif not v and ini is not None:
            dur = (i - ini) * 0.01 / vel
            fim_do_video = i >= n - 1
            if dur >= minimo and ini > 0 and not fim_do_video:
                achados.append((ini * 0.01 / vel, dur))
            ini = None
    return achados


def leitor():
    if os.path.exists(LEITOR) and os.path.getmtime(LEITOR) >= os.path.getmtime(os.path.join(AQUI, "ocr_vision.swift")):
        return LEITOR
    if not shutil.which("swiftc"):
        return None
    os.makedirs(os.path.dirname(LEITOR), exist_ok=True)
    r = rodar(["swiftc", "-O", os.path.join(AQUI, "ocr_vision.swift"), "-o", LEITOR])
    return LEITOR if r.returncode == 0 else None


def ler_texto(video, fps, pasta):
    rodar(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={fps}", "-q:v", "3", os.path.join(pasta, "f_%05d.jpg")])
    exe = leitor()
    if not exe:
        return None
    saida = os.path.join(pasta, "ocr.json")
    rodar([exe, pasta, saida])
    with open(saida) as f:
        return json.load(f)


def agrupar(eventos, junta=1.0):
    """[(t, texto)] -> [(t0, t1, {textos})], unindo o que aparece a menos de 'junta' s."""
    grupos = []
    for t, txt in sorted(eventos):
        if grupos and t - grupos[-1][1] <= junta:
            grupos[-1][1] = t
            grupos[-1][2].add(txt)
        else:
            grupos.append([t, t, {txt}])
    return grupos


def folha(pasta, fps, destino, colunas=10, largura=216):
    quadros = sorted(n for n in os.listdir(pasta) if n.startswith("f_"))
    passo = max(1, len(quadros) // 60)
    quadros = quadros[::passo]
    alt = int(largura * 1920 / 1080)
    linhas = (len(quadros) + colunas - 1) // colunas
    sheet = Image.new("RGB", (colunas * largura, linhas * (alt + 18)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    esc = largura / 1080
    for i, nome in enumerate(quadros):
        img = Image.open(os.path.join(pasta, nome)).convert("RGB").resize((largura, alt))
        x, y = (i % colunas) * largura, (i // colunas) * (alt + 18)
        sheet.paste(img, (x, y))
        d.rectangle([x + ZONA[0] * esc, y + ZONA[1] * esc, x + ZONA[2] * esc, y + ZONA[3] * esc], outline=(255, 60, 60))
        t = (int(nome[2:7]) - 1) / fps
        d.text((x + 4, y + alt + 3), f"{int(t // 60)}:{t % 60:04.1f}", fill=(230, 230, 230))
    sheet.save(destino, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--trab")
    ap.add_argument("--velocidade", type=float, default=1.12)
    ap.add_argument("--fps", type=float, default=2)
    a = ap.parse_args()
    ruim = 0
    nome = os.path.basename(a.video)
    print(f"== {nome}")

    pr = preto(a.video)
    print(f"[{'OK' if not pr else 'OLHAR'}] quadro preto" + "".join(f"\n      {s:.2f}s a {e:.2f}s" for s, e in pr))
    ruim += bool(pr)

    lufs, pico = volume(a.video)
    ok = abs(lufs + 15) <= 1.5 and (pico is None or pico < -1)
    print(f"[{'OK' if ok else 'OLHAR'}] volume {lufs:.1f} LUFS, pico {pico} dBFS")
    ruim += not ok

    voz = os.path.join(a.trab, "voz_crua.wav") if a.trab else None
    if voz and os.path.exists(voz):
        rs = respiros(voz, a.velocidade)
        print(f"[{'OK' if not rs else 'OLHAR'}] respiros de 0,25 s ou mais: {len(rs)}"
              + "".join(f"\n      {t:6.2f}s  {d:.2f}s" for t, d in rs))
        ruim += bool(rs)
    else:
        print("[--] respiros: sem voz_crua.wav (passe --trab)")

    with tempfile.TemporaryDirectory() as pasta:
        ocr = ler_texto(a.video, a.fps, pasta)
        if ocr is None:
            print("[--] texto: sem leitor (xcode-select --install traz o swiftc); olhe a folha de quadros")
        else:
            fora, dados = [], []
            for arq, itens in ocr.items():
                t = (int(arq[2:7]) - 1) / a.fps
                for it in itens:
                    if it["c"] < 0.5 or len(it["t"].strip()) < 2:
                        continue
                    x0, x1 = it["x"] * 1080, (it["x"] + it["w"]) * 1080
                    y0, y1 = (1 - it["y"] - it["h"]) * 1920, (1 - it["y"]) * 1920
                    # Só texto grande (40 px ou mais) é da edição; letra miúda é tela do sistema ou print.
                    if y1 - y0 >= 40 and (x0 < ZONA[0] or x1 > ZONA[2] or y0 < ZONA[1] or y1 > ZONA[3]):
                        lado = "topo" if y0 < ZONA[1] else "baixo" if y1 > ZONA[3] else "lateral"
                        fora.append((t, f"{it['t'].strip()} ({lado}, y {y0:.0f}-{y1:.0f})"))
                    if any(x in it["t"].lower() for x in IGNORAR):
                        continue
                    for tipo, rx in PADROES.items():
                        for achado in rx.findall(it["t"]) if tipo != "telefone" else [m.group(0) for m in rx.finditer(it["t"])]:
                            if tipo == "telefone" and len(re.sub(r"\D", "", achado)) < 10:
                                continue
                            dados.append((t, f"{tipo}: {it['t'].strip()}"))
            gf, gd = agrupar(fora), agrupar(dados)
            print(f"[{'OK' if not gf else 'OLHAR'}] texto grande fora da zona segura: {len(gf)} trechos")
            for t0, t1, txt in gf:
                print(f"      {t0:6.1f}-{t1:5.1f}s  " + " | ".join(sorted(txt))[:150])
            print(f"[{'OK' if not gd else 'OLHAR'}] dado pessoal legível: {len(gd)} trechos")
            for t0, t1, txt in gd:
                print(f"      {t0:6.1f}-{t1:5.1f}s  " + " | ".join(sorted(txt))[:150])
            ruim += bool(gf) + bool(gd)
        destino = os.path.splitext(a.video)[0] + "_portao.jpg"
        if a.trab:
            destino = os.path.join(a.trab, os.path.basename(destino))
        folha(pasta, a.fps, destino)
        print(f"folha: {destino}")
    print("PASSOU" if not ruim else f"OLHAR: {ruim} item(ns)")
    return 1 if ruim else 0


if __name__ == "__main__":
    sys.exit(main())
