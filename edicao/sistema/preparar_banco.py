"""Converte os takes HDR (HLG) do banco para SDR BT.709 uma vez so.
Uso: python3 preparar_banco.py <pasta_saida> <arquivo relativo ao banco>...
     python3 preparar_banco.py <pasta_saida> tudo   (acha sozinho todo video HDR do banco)
Clipe HDR sem converter entra na edicao com a cor errada e sem aviso.
"""
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

_EDICAO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO = os.environ.get("EDICAO_BANCO", os.path.join(_EDICAO, "banco"))
PRONTO = os.environ.get("EDICAO_BANCO_SDR", os.path.join(_EDICAO, "banco_sdr"))


def sonda(src, campo):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", f"stream={campo}",
                           "-of", "csv=p=0", src], capture_output=True, text=True, check=True).stdout.strip().split(",")[0]


def converter_sdr(src, dst):
    """Grava dst em BT.709 a 30 fps. Passa por .tmp.mov para nao deixar arquivo pela metade."""
    preset = "Preset3840x2160" if int(sonda(src, "width")) >= 3000 else "Preset1920x1080"
    tmp = dst + ".tmp.mov"
    if shutil.which("avconvert"):  # macOS: melhor cor
        subprocess.run(["avconvert", "-p", preset, "-s", src, "-o", tmp, "--replace"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:  # outros sistemas: tone mapping do ffmpeg (precisa de ffmpeg com zimg)
        vf = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
              "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf, "-r", "30", "-c:v", "libx264", "-crf", "16",
                        "-c:a", "aac", "-f", "mov", tmp], check=True)
    os.rename(tmp, dst)


def videos_hdr():
    achados = []
    for raiz, _, nomes in os.walk(BANCO):
        for nome in nomes:
            if nome.lower().endswith((".mov", ".mp4")):
                caminho = os.path.join(raiz, nome)
                if sonda(caminho, "color_transfer") in ("arib-std-b67", "smpte2084"):
                    achados.append(os.path.relpath(caminho, BANCO))
    return sorted(achados)


def destino(saida, rel):
    return os.path.join(saida, rel.replace("/", "__").rsplit(".", 1)[0] + ".mov")


def um(args):
    saida, rel = args
    dst = destino(saida, rel)
    if os.path.exists(dst):
        return rel, "cache"
    nome = os.path.basename(rel).rsplit(".", 1)[0]
    pasta = {"takes": "video1", "ep2": "ep2"}.get(rel.split("/")[0], "")
    feito = os.path.join(PRONTO, pasta, nome + ".mov")
    if os.path.exists(feito):
        os.symlink(feito, dst)
        return rel, "reaproveitado"
    converter_sdr(os.path.join(BANCO, rel), dst)
    return rel, "convertido"


if __name__ == "__main__":
    saida = sys.argv[1]
    os.makedirs(saida, exist_ok=True)
    lista = videos_hdr() if sys.argv[2:] == ["tudo"] else sys.argv[2:]
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(um, [(saida, x) for x in lista]):
            print(*r, flush=True)


def sdr_ou_converte(nome, banco_sdr):
    """Caminho do clipe pronto para a edição: a cópia SDR quando o original é HDR (convertida na hora, uma vez só);
    senão o original. Clipe HDR sem conversão entra lavado, sem aviso."""
    original = os.path.join(BANCO, nome)
    dst = destino(banco_sdr, nome)
    if os.path.exists(dst):
        return dst
    if not os.path.exists(original) or sonda(original, "color_transfer") not in ("arib-std-b67", "smpte2084"):
        return original
    os.makedirs(banco_sdr, exist_ok=True)
    print(f"convertendo HDR para SDR: {nome}", flush=True)
    um((banco_sdr, nome))
    return dst
