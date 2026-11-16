"""O que todos os planos compartilham: caminhos, trilhas e o mapa dos brutos.

Tudo fica dentro da pasta edicao/ do repositório. Para usar outro lugar, defina as variáveis de ambiente:
  EDICAO_SCRATCH   pasta de trabalho temporária (padrão: edicao/.trabalho)
  EDICAO_BANCO     banco de cenas de apoio      (padrão: edicao/banco)
  EDICAO_MUSICAS   trilhas                      (padrão: edicao/musicas)
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../edicao
BANCO = os.environ.get("EDICAO_BANCO", f"{RAIZ}/banco")
BANCO_SDR = os.environ.get("EDICAO_BANCO_SDR", f"{RAIZ}/banco_sdr")  # cópias SDR dos clipes HDR (permanente)
PROVAS = f"{BANCO}/provas"  # prints de depoimento (com autorização, sem dado pessoal visível)
MUSICAS = os.environ.get("EDICAO_MUSICAS", f"{RAIZ}/musicas")
SCRATCH = os.environ.get("EDICAO_SCRATCH", f"{RAIZ}/.trabalho")

# Uma faixa por emoção. Coloque em edicao/musicas um arquivo com cada nome (use só música com licença comercial).
FAIXAS = {nome: f"{nome}.mp3" for nome in
          ("abertura", "mercado", "piano", "virada", "misterio", "rock", "cordas", "alegre")}


def nomes_cru(cru):
    """take -> caminho relativo. Aceita 'IMG_5003 3.MOV', '.mov' minúsculo e subpastas."""
    nomes = {}
    for raiz, _, arquivos in os.walk(cru):
        for nome in arquivos:
            achou = re.match(r"IMG_(\d+).*\.mov$", nome, re.I)
            if achou:
                nomes[achou.group(1)] = os.path.relpath(os.path.join(raiz, nome), cru)
    return nomes


def emprestar(sdr, wavs, txt, take, origem):
    """Traz um take de outro ad (já preparado) para este plano, com vídeo, áudio e transcrição.
    origem = id do plano de onde vem o take (ex.: 'exemplo'). Devolve o caminho do bruto."""
    for destino, sub, ext in ((sdr, "sdr", "mov"), (wavs, "wav", "wav"), (txt, "txt", "json")):
        os.makedirs(destino, exist_ok=True)
        link = f"{destino}/IMG_{take}.{ext}"
        if not os.path.lexists(link):
            os.symlink(f"{SCRATCH}/{origem}/{sub}/IMG_{take}.{ext}", link)
    import importlib
    cru = importlib.import_module(origem).CRU
    return os.path.join(cru, nomes_cru(cru)[take])
