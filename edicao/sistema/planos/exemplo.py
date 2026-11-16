"""Plano de exemplo. Copie este arquivo para planos/<id>.py e troque pelos seus takes.

Fluxo:
  1. Grave os takes no celular (um trecho de fala por arquivo) e coloque em edicao/brutos/<id>/.
  2. python3 preparar_brutos.py <id>   → converte, extrai o áudio e transcreve (txt/IMG_xxxx.json).
  3. Escreva aqui o texto corrigido de cada take (TOMADAS), com *destaques* entre asteriscos.
  4. Escreva as cenas no gerar_<id>.py e rode: python3 gerar_<id>.py base (só cenas) ou tudo (vídeo final).

Os números abaixo (0001…0006) são o número do arquivo IMG_0001.MOV etc.
"""
import os

from comum import *  # noqa: F401,F403
from comum import RAIZ, SCRATCH, nomes_cru

ID = "exemplo"
CRU = f"{RAIZ}/brutos/{ID}"
SDR = f"{SCRATCH}/{ID}/sdr"
WAVS = f"{SCRATCH}/{ID}/wav"
TXT = f"{SCRATCH}/{ID}/txt"
CRU_NOMES = nomes_cru(CRU) if os.path.isdir(CRU) else {}
GANCHO = os.environ.get("EDICAO_GANCHO", "1")  # para ter mais de um gancho com o mesmo corpo
SAIDA = f"{RAIZ}/saida/{ID}.mp4"

ONDA = True            # tempo de cada palavra ajustado pela onda do áudio
ZONA_SEGURA = True     # nada importante nas faixas que a interface do Reels/TikTok cobre
LIMPAR_INICIO = True   # corta o silêncio antes da primeira palavra de cada take
TRILHA_RMS = -30       # nível da trilha (a voz é mixada por cima e o final sai em -15 LUFS)
MAX_PLANO = 4.5        # plano de rosto mais longo antes de trocar o zoom
LEGENDA_Y = 1170       # altura da legenda (desce sozinha se o rosto estiver ali)
MIN_FALA = 2.0         # tempo mínimo de rosto entre duas cenas de apoio
MAX_CENA = 3.0
VELOCIDADE = 1.1       # acelera o vídeo final
SONS_VARIADOS = True
TEMA_LEGENDA = "classica"  # classica | karaoke | faixa | gigante
GRAFISMOS = ["pilula", "etiqueta"]
PRIMEIRA_DO_CORPO = "0003"

# Texto corrigido de cada take, na ordem do vídeo. *palavra* vira destaque na legenda.
# Opções por take: "janela": (ini, fim) em segundos no bruto, "cortes": [(a, b)], "inicio_exato": True.
TOMADAS = {
    "0001": {"texto": "Você sabia que *dá pra começar* com o que você já tem em casa?"},
    "0002": {"texto": "Eu vou te mostrar *o caminho* em menos de um minuto."},
    "0003": {"texto": "Primeiro: você não precisa de *estoque*, nem de *mostrar o rosto*."},
    "0004": {"texto": "Ah, mas e como eu vou *divulgar*?"},
    "0005": {"texto": "A ferramenta já te mostra os *vídeos que estão bombando* do seu produto."},
    "0006": {"texto": "Então *toca em saiba mais* e assiste a aula enquanto ela está no ar."},
}

# Objeção de alguém imitada pela pessoa: voz levemente distorcida e quadro cinza.
DISTORCER = [("0004", "Ah", "divulgar")]
PRETO_E_BRANCO = [("0004", "Ah", "divulgar")]

# Blocos de emoção: cada um escolhe a cor da legenda, a faixa (nome em comum.FAIXAS), onde a música começa e o ganho.
BLOCOS = [
    {"takes": ["0001", "0002"], "emocao": "gancho", "faixa": "mercado", "ini": 8, "ganho": -1},
    {"takes": ["0003", "0004"], "emocao": "tensao", "faixa": "misterio", "ini": 30, "ganho": -1},
    {"takes": ["0005"], "emocao": "empolgacao", "faixa": "rock", "ini": 18, "ganho": 2},
    {"takes": ["0006"], "emocao": "urgencia", "faixa": "rock", "ini": 60, "ganho": 3},
]
ESTILO_FORCADO = {("0006", "toca"): "impacto"}
