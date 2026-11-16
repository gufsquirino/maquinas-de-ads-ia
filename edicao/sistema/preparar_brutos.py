"""Prepara os brutos de um ad: video SDR, audio 16 kHz e transcricao com tempo por palavra. Pode rodar de novo.

Uso: EDICAO_SCRATCH=<pasta> python3 preparar_brutos.py <id do plano, ex: exemplo> ["termos, da, oferta"]

Le o plano e grava em p.SDR, p.WAVS e p.TXT. Para cada take, IMG_xxxx.json tem os tempos (Whisper small)
e IMG_xxxx.large.txt, quando ha whisper-cli, tem o texto mais fiel para corrigir o plano.
"""
import glob
import importlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [AQUI, os.path.join(AQUI, "planos")]

from preparar_banco import converter_sdr  # noqa: E402

# Vocabulário que ajuda o Whisper: nome da pessoa, do produto e termos do nicho. Troque em EDICAO_TERMOS.
TERMOS = os.environ.get("EDICAO_TERMOS", "loja virtual, renda extra, afiliado, fornecedor, nicho")
MODELO_LARGE = os.path.expanduser("~/.cache/whisper/ggml-large-v3-turbo.bin")


def achar_brutos(p):
    """Nome interno de cada bruto: IMG_4483, mesmo quando o arquivo se chama gancho2-IMG_4483.MOV."""
    apelidos = {os.path.normpath(os.path.join(p.CRU, rel)): f"IMG_{take}"
                for take, rel in getattr(p, "CRU_NOMES", {}).items()}
    brutos = {}
    for raiz, _, nomes in os.walk(p.CRU):
        for nome in nomes:
            if nome.lower().endswith((".mov", ".mp4")):
                caminho = os.path.normpath(os.path.join(raiz, nome))
                brutos[apelidos.get(caminho, os.path.splitext(nome)[0])] = caminho
    return dict(sorted(brutos.items()))


def preparar_um(args):
    p, nome, src = args
    sdr = os.path.join(p.SDR, f"{nome}.mov")
    wav = os.path.join(p.WAVS, f"{nome}.wav")
    if not os.path.exists(sdr):
        converter_sdr(src, sdr)
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    print("video e audio ok:", nome, flush=True)


def transcrever(p, nomes, termos):
    pendentes = [n for n in nomes if not os.path.exists(os.path.join(p.TXT, f"{n}.json"))]
    cli = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if cli and os.path.exists(MODELO_LARGE):
        for n in nomes:
            destino = os.path.join(p.TXT, f"{n}.large.txt")
            if not os.path.exists(destino):
                r = subprocess.run([cli, "-m", MODELO_LARGE, "-l", "pt", "-nt", "--prompt", termos,
                                    "-f", os.path.join(p.WAVS, f"{n}.wav")], capture_output=True, text=True, check=True)
                with open(destino, "w", encoding="utf-8") as f:
                    f.write(" ".join(r.stdout.split()))
    else:
        print("Sem whisper-cli: seguindo so com o Whisper small.", flush=True)
    if pendentes:
        import whisper
        modelo = whisper.load_model("small")
        for n in pendentes:
            # Prompt longo faz o Whisper alucinar, por isso so vocabulario e sem herdar o texto anterior.
            r = modelo.transcribe(os.path.join(p.WAVS, f"{n}.wav"), language="pt", word_timestamps=True, fp16=False,
                                  initial_prompt=termos, condition_on_previous_text=False, verbose=False)
            with open(os.path.join(p.TXT, f"{n}.json"), "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, default=float)
            print("transcrito:", n, flush=True)


def main():
    p = importlib.import_module(sys.argv[1])
    termos = sys.argv[2] if len(sys.argv) > 2 else TERMOS
    for pasta in (p.SDR, p.WAVS, p.TXT):
        os.makedirs(pasta, exist_ok=True)
    brutos = achar_brutos(p)
    if not brutos:
        sys.exit(f"Nenhum .MOV ou .MP4 em {p.CRU}")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(preparar_um, [(p, n, c) for n, c in brutos.items()]))
    transcrever(p, list(brutos), termos)
    faltam = [t for t in p.TOMADAS if f"IMG_{t}" not in brutos]
    print(f"FIM: {len(brutos)} brutos. Tomadas do plano sem bruto: {faltam or 'nenhuma'}")


if __name__ == "__main__":
    main()
