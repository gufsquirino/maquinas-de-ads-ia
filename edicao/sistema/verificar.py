"""Confere se este computador esta pronto para a maquina de edicao. Nao altera nada.
Uso: python3 verificar.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CASA = os.path.expanduser("~")
falhas = 0


def checar(nome, ok, ajuda=""):
    global falhas
    falhas += not ok
    print(f"[{'OK' if ok else 'FALTA'}] {nome}" + (f"\n        -> {ajuda}" if not ok and ajuda else ""))


def saida(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout
    except OSError:
        return ""


def contar(pasta):
    return sum(len(a) for _, _, a in os.walk(pasta))


print(f"Python {sys.version.split()[0]}\n")

print("Programas")
ffmpeg = shutil.which("ffmpeg")
checar("ffmpeg", ffmpeg, "brew install ffmpeg-full e coloque no PATH")
checar("ffprobe", shutil.which("ffprobe"))
filtros = saida(["ffmpeg", "-hide_banner", "-filters"]) if ffmpeg else ""
for filtro, motivo in (("ass", "legendas"), ("tpad", "sobreposicoes"), ("ebur128", "volume")):
    checar(f"filtro {filtro} ({motivo})", f" {filtro} " in filtros, "Este ffmpeg esta incompleto: use o ffmpeg-full")
for prog in ("swiftc",):
    checar(prog + " (rostos e leitura de texto, macOS)", shutil.which(prog), "Instale as ferramentas da Apple: xcode-select --install")

print("\nBibliotecas do Python")
for mod in ("numpy", "PIL", "whisper"):
    checar(mod, importlib.util.find_spec(mod), f"pip install -r {os.path.join(AQUI, 'requirements.txt')}")

print("\nArquivos")
for fonte in ("Montserrat-Black", "Anton-Regular", "Excalifont-Regular", "InstrumentSerif-Italic"):
    checar(f"fonte {fonte}", os.path.exists(os.path.join(AQUI, "fontes", f"{fonte}.ttf")))
EDICAO = os.path.dirname(AQUI)
musicas = os.path.join(EDICAO, "musicas")
faltam = [n for n in ("abertura", "mercado", "piano", "virada", "misterio", "rock", "cordas", "alegre")
          if not os.path.exists(os.path.join(musicas, f"{n}.mp3"))]
checar(f"trilhas em edicao/musicas ({8 - len(faltam)} de 8)", not faltam, f"Faltam: {', '.join(faltam)} (.mp3 com licença comercial)")
banco = os.path.join(EDICAO, "banco")
print(f"[{'OK' if contar(banco) > 1 else '--'}] banco de cenas: {contar(banco)} arquivos em edicao/banco")
print(f"[{'OK' if contar(os.path.join(banco, 'provas')) > 1 else '--'}] prints de depoimento em edicao/banco/provas")

print("\nOpcional")
print(f"[{'OK' if shutil.which('whisper-cli') else '--'}] whisper-cli (transcrição mais fiel para conferir o texto)")
fx = os.environ.get("EDICAO_FX", "")
print(f"[{'OK' if fx and os.path.isfile(os.path.join(fx, 'scripts', 'fx.py')) else '--'}] efeitos de vídeo (EDICAO_FX)")
livre = shutil.disk_usage(CASA).free / 1024 ** 3
print(f"[{'OK' if livre >= 30 else '!!'}] espaco livre: {livre:.0f} GB (recomendado: 30 GB ou mais)")

print(f"\n{'TUDO CERTO' if not falhas else f'{falhas} item(ns) faltando'}")
sys.exit(1 if falhas else 0)
