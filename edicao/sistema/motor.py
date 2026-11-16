"""Motor de edicao de ads: cortes, zooms, legendas, grafismos, sons e render.

Recebe um plano (veja planos/exemplo.py) e gera o MP4 final em 1080x1920.
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import sons

FPS = 30
W, H = 1080, 1920
SR = 48000
AQUI = os.path.dirname(os.path.abspath(__file__))
FONTE_BLACK = os.path.join(AQUI, "fontes", "Montserrat-Black.ttf")
FONTES_LEG = {
    "L": os.path.join(AQUI, "fontes", "Montserrat-Black.ttf"),
    "A": os.path.join(AQUI, "fontes", "Anton-Regular.ttf"),
    "M": os.path.join(AQUI, "fontes", "Excalifont-Regular.ttf"),
    "E": os.path.join(AQUI, "fontes", "InstrumentSerif-Italic.ttf"),
}
# Cor do destaque por emocao: (ASS BGR do texto, caixa, texto sobre a caixa)
CORES = {
    "amarelo": ("&H0000D5FF&", "&H0000D5FF&", "&H00101010&"),
    "vermelho": ("&H00463BFF&", "&H00302AE0&", "&H00FFFFFF&"),
    "verde": ("&H0033FF9E&", "&H005EC516&", "&H00101010&"),
    "branco": ("&H00FFFFFF&", "&H00FFFFFF&", "&H00101010&"),
}
# Cada emocao percorre sua propria sequencia de estilos e tem sua cor.
ROTA = {
    "gancho": ("amarelo", ["impacto", "manuscrita", "empilhada"]),
    "tensao": ("vermelho", ["impacto", "caixa", "empilhada", "impacto"]),
    "virada": ("amarelo", ["empilhada", "caixa", "manuscrita", "impacto"]),
    "historia": ("branco", ["elegante", "impacto", "elegante", "manuscrita"]),
    "empolgacao": ("amarelo", ["impacto", "manuscrita", "caixa", "empilhada"]),
    "vitoria": ("verde", ["manuscrita", "impacto", "caixa", "empilhada"]),
    "urgencia": ("vermelho", ["caixa", "impacto", "empilhada"]),
    "convite": ("verde", ["elegante", "manuscrita", "empilhada", "caixa"]),
}
# Temas de legenda: cada ad escolhe um em TEMA_LEGENDA para os criativos não saírem iguais.
# "base" é como o texto corrido aparece; "rota" troca a sequência de destaques por emoção.
TEMAS = {
    "classica": {},
    "karaoke": {"base": "karaoke", "rota": {e: ["caixa", "impacto"] for e in ROTA}},
    "faixa": {"base": "faixa", "rota": {e: ["manuscrita", "empilhada", "elegante"] for e in ROTA}},
    "gigante": {"base": "gigante", "rota": {e: ["impacto", "manuscrita"] for e in ROTA}},
}
EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"
AMARELO = "&H0000D5FF&"
VERDE = (22, 197, 94, 255)
VERMELHO = (229, 40, 62, 255)
BRANCO = (255, 255, 255, 255)
GANHO_SOM = {
    "whoosh": -15, "whoosh_curto": -19, "pop": -14, "tick": -18, "ding": -17,
    "sucesso": -15, "erro": -18, "impacto": -11, "caixa": -16, "subida": -19,
    "moeda": -17, "registradora": -17, "swoosh": -18, "swoosh_grave": -17, "brilho": -19, "vinil": -17, "boing": -18,
}


def distorcer_trecho(voz, t0, t1, intensidade=0.4):
    """Efeito leve de rádio na objeção que ela imita. A voz original continua por baixo. Altera voz no lugar."""
    a, b = int(max(t0, 0) * SR), min(int(t1 * SR), len(voz))
    if b - a < SR // 10:
        return
    x = voz[a:b]
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    y = sons.banda(np.tanh(x / rms * 1.3), 320, 3400)
    y = y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * rms
    y = x * (1 - intensidade) + y * intensidade
    cruz = min(int(0.02 * SR), (b - a) // 2)
    env = np.ones(b - a)
    env[:cruz] = np.linspace(0, 1, cruz)
    env[-cruz:] = np.linspace(1, 0, cruz)
    voz[a:b] = x * (1 - env) + y * env


def igualar_voz(voz, t0, t1, extra=0.0, antes=5.0):
    """Leva um take de outro ad ao nível da fala anterior, palavra por palavra. Altera voz no lugar."""
    hop = int(0.02 * SR)
    janela = np.ones(10) / 10

    def nivel(a, b):
        x = voz[a:b]
        n = len(x) // hop
        e = np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)
        return 10 * np.log10(np.convolve(e, janela, mode="same") + 1e-12)

    a, b = int(t0 * SR), min(int(t1 * SR), len(voz))
    previo = nivel(max(a - int(antes * SR), 0), a)
    alvo = np.median(previo[previo > np.percentile(previo, 95) - 14]) + extra
    env = nivel(a, b)
    falando = env > alvo - 22
    if not falando.any():
        return
    ganho = np.where(falando, np.clip(alvo - env, -12, 10), np.nan)
    pos = np.arange(len(ganho))
    ganho = np.interp(pos, pos[falando], ganho[falando])
    ganho = np.convolve(np.pad(ganho, 5, mode="edge"), janela, mode="same")[5:-5]
    amostras = np.interp(np.arange(b - a), (pos + 0.5) * hop, ganho)
    voz[a:b] *= 10 ** (amostras / 20)
    print(f"igualar {t0:.1f}-{t1:.1f}s alvo={alvo:.1f} dB ganho medio={np.mean(ganho):+.1f} dB", flush=True)


def rodar(cmd, **kw):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)


def norm(p):
    return re.sub(r"[^\w%]", "", p.lower())


# ---------------------------------------------------------------- texto e tempo
def parse_texto(texto):
    tokens, destaque = [], False
    for bruto in texto.split():
        abre = bruto.startswith("*")
        fecha = bruto.rstrip(".,?!").endswith("*")
        limpo = bruto.replace("*", "")
        if abre:
            destaque = True
        tokens.append({"txt": limpo, "dest": destaque, "fim_frase": limpo[-1] in ".,?!"})
        if fecha:
            destaque = False
    return tokens


def alinhar(tokens, palavras):
    """Passa os tempos do Whisper para o texto corrigido."""
    a = [norm(t["txt"]) for t in tokens]
    b = [norm(p["word"]) for p in palavras]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    inicio = [None] * len(a)
    fim = [None] * len(a)
    for bloco in sm.get_matching_blocks():
        for k in range(bloco.size):
            inicio[bloco.a + k] = palavras[bloco.b + k]["start"]
            fim[bloco.a + k] = palavras[bloco.b + k]["end"]
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or i2 == i1:
            continue
        ini = palavras[j1]["start"] if j1 < len(palavras) and j2 > j1 else (fim[i1 - 1] if i1 else 0)
        fi = palavras[j2 - 1]["end"] if j2 > j1 else (inicio[i2] if i2 < len(a) and inicio[i2] else ini + 0.25 * (i2 - i1))
        passo = (fi - ini) / (i2 - i1)
        for k in range(i1, i2):
            inicio[k] = ini + passo * (k - i1)
            fim[k] = ini + passo * (k - i1 + 1)
    for t, s, e in zip(tokens, inicio, fim):
        t["s"], t["e"] = float(s), float(e)
    return tokens


def inicio_fala(wav, desde=0.0):
    """Onde comeca a voz forte de quem fala. A voz de quem grava ("vai", "pode ir") fica cerca de 20 dB abaixo."""
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
    hop = 320
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    limiar = np.percentile(db, 95) - 18
    piso = int(desde / 0.02)
    for i in range(piso, n - 15):
        # 0,3 s sustentados: a voz de quem grava é curta e não passa disso.
        if db[i] > limiar and np.mean(db[i:i + 15]) > limiar:
            # Sílaba fraca ("Te", "Sim"): recua até o silêncio que separa a fala da voz de quem grava.
            ini = i
            while ini > max(piso, i - 18) and not np.all(db[max(ini - 3, 0):ini] < -54):
                ini -= 1
            return ini * 0.02
    return desde


def envelope_10ms(wav):
    """dB da voz em janelas de 10 ms (índice 0 = tempo 0 do take)."""
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
    hop = 160
    n = len(x) // hop
    return 10 * np.log10(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)


def limiar_pausa(db):
    """Chão de ruído + 14 dB, nunca mais de 28 dB abaixo da fala forte."""
    chao, forte = float(np.percentile(db, 10)), float(np.percentile(db, 90))
    return min(max(chao + 14, forte - 28), forte - 20)


def palavras_na_onda(wav, toks):
    """Corrige o início de cada palavra pela onda: o Whisper adianta até 0,3 s, e grafismo, som e cena entram
    na palavra. Depois de uma pausa, o início é o primeiro som sustentado; sem pausa, a subida depois do vale
    mais fundo (10 dB) perto do tempo do Whisper. Sem nada para medir, fica o tempo do Whisper.
    Devolve quantas palavras andaram 0,05 s ou mais."""
    db = envelope_10ms(wav)
    th = limiar_pausa(db)
    hop, movidas, anterior = 0.01, 0, None
    for i, t in enumerate(toks):
        s, e = t["s"], t["e"]
        lo = max((anterior + 0.05) if anterior is not None else 0.0, s - 0.10, 0.0)
        ate = max(s + 0.40, e - 0.02)
        if i + 1 < len(toks):
            ate = min(ate, toks[i + 1]["s"])
        hi = max(lo + hop, max(ate, s + 0.05))
        i0, i1 = int(round(lo / hop)), min(len(db), int(round(hi / hop)))
        novo = s
        if i1 - i0 >= 2:
            seg = db[i0:i1]
            cands, quieto = [], 0
            for k in range(len(seg)):
                if seg[k] < th:
                    quieto += 1
                    continue
                if quieto >= 3 and k + 4 <= len(seg) and bool((seg[k:k + 4] >= th).all()):
                    cands.append(k)
                quieto = 0
            if cands:
                w = int(round(s / hop)) - i0
                depois = [k for k in cands if k >= w - 5]
                novo = (i0 + (depois[0] if depois else cands[-1])) * hop
            else:
                j0 = max(0, int(round((s - 0.08) / hop)) - i0)
                j1 = min(len(seg), int(round((s + 0.20) / hop)) - i0)
                if j1 - j0 >= 3:
                    k = j0 + int(np.argmin(seg[j0:j1]))
                    adiante = seg[k:k + 15]
                    if len(adiante) and adiante.max() - seg[k] >= 10:
                        meio = seg[k] + (adiante.max() - seg[k]) / 2
                        novo = (i0 + k + int(np.argmax(adiante >= meio))) * hop
        if abs(novo - s) >= 0.05:
            movidas += 1
        t["s_whisper"] = s
        t["s"] = float(novo)
        t["e"] = float(max(e, novo + 0.05))
        anterior = t["s"]
    return movidas


def trechos_voz(wav, janela):
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
    hop = 320
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    limiar = max(-44, np.percentile(db, 95) - 30)
    voz = db > limiar
    runs, ini = [], None
    for i, v in enumerate(voz):
        t = i * 0.02
        if v and ini is None:
            ini = t
        if not v and ini is not None:
            runs.append([ini, t])
            ini = None
    if ini is not None:
        runs.append([ini, n * 0.02])
    unidos = []
    for r in runs:
        if unidos and r[0] - unidos[-1][1] < 0.2:
            unidos[-1][1] = r[1]
        else:
            unidos.append(r)
    a, b = janela
    fim = len(x) / 16000
    saida = []
    for s, e in unidos:
        s, e = max(s - 0.05, a), min(e + 0.09, b, fim)
        if e - s >= 0.12:
            saida.append([s, e])
    return saida


# ---------------------------------------------------------------- plano de cortes
class Edicao:
    def __init__(self, plano, trabalho):
        self.p = plano
        self.t = trabalho
        os.makedirs(trabalho, exist_ok=True)
        self.tokens = {}
        self.shots = []
        self.sons = []
        self.overlays = []
        self.cap_y = []
        self.cenas = []
        self.sem_legenda = []

    def preparar(self):
        for i, (take, cfg) in enumerate(self.p.TOMADAS.items()):
            with open(os.path.join(self.p.TXT, f"IMG_{take}.json")) as f:
                r = json.load(f)
            pal = [w for s in r["segments"] for w in s.get("words", [])]
            # "trocas" corrige palavra que o Whisper errou e fazia o alinhamento pular para outra igual.
            trocas = cfg.get("trocas", {})
            pal = [{**w, "word": trocas.get(w["word"].strip(), w["word"])} for w in pal]
            toks = alinhar(parse_texto(cfg["texto"]), pal)
            jan = cfg.get("janela", (toks[0]["s"] - 0.3, toks[-1]["e"] + 0.3))
            wav = os.path.join(self.p.WAVS, f"IMG_{take}.wav")
            if getattr(self.p, "ONDA", False):
                self.palavras_movidas = getattr(self, "palavras_movidas", 0) + palavras_na_onda(wav, toks)
            if getattr(self.p, "LIMPAR_INICIO", False) and not cfg.get("inicio_exato"):
                jan = (max(jan[0], inicio_fala(wav, jan[0]) - 0.06), jan[1])
            runs = trechos_voz(wav, jan)
            for a, b in cfg.get("cortes", []):
                novos = []
                for s, e in runs:
                    if e <= a or s >= b:
                        novos.append([s, e])
                    else:
                        if s < a:
                            novos.append([s, a])
                        if e > b:
                            novos.append([b, e])
                runs = novos
            for t in toks:
                t["take"] = take
                # O Whisper costuma marcar o 1o "E" em 0.00; prende ao inicio real da voz.
                if t["s"] < runs[0][0]:
                    t["s"] = runs[0][0]
                    t["e"] = max(t["e"], t["s"] + 0.08)
            self.tokens[take] = toks
            self._cortar(take, cfg, runs, toks)
        self._quantizar()

    def _pb_faixas(self, take):
        faixas = []
        for tk, a, b in self.p.PRETO_E_BRANCO:
            if tk == take:
                toks = self.tokens[take]
                faixas.append((self._acha(toks, a)["s"] - 0.03, self._acha(toks, b)["e"] + 0.03))
        return faixas

    def _acha(self, toks, palavra, n=0):
        ach = [t for t in toks if norm(t["txt"]).startswith(norm(palavra))]
        if not ach:
            raise ValueError(f"palavra nao encontrada: {palavra} em {toks[0]['take']}")
        return ach[n]

    def _cortar(self, take, cfg, runs, toks):
        pb = self._pb_faixas(take)
        for s, e in runs:
            quebras = {s, e}
            for a, b in pb:
                for q in (a, b):
                    if s + 0.15 < q < e - 0.15:
                        quebras.add(q)
            pontos = sorted(quebras)
            finais = []
            for a, b in zip(pontos, pontos[1:]):
                cur = a
                while b - cur > self.p.MAX_PLANO:
                    alvo = cur + self.p.MAX_PLANO * 0.8
                    cands = [t["s"] for t in toks if cur + 1.0 < t["s"] < b - 0.6]
                    if not cands:
                        break
                    corte = min(cands, key=lambda x: abs(x - alvo))
                    finais.append((cur, corte))
                    cur = corte
                finais.append((cur, b))
            for a, b in finais:
                meio = (a + b) / 2
                bw = any(x <= meio <= y for x, y in pb)
                self.shots.append({"take": take, "s": a, "e": b, "bw": bw, "wide": cfg.get("wide", False)})

    def _quantizar(self):
        off, saida = 0, []
        for sh in self.shots:
            f0, f1 = round(sh["s"] * FPS), round(sh["e"] * FPS)
            if f1 - f0 < 4:
                continue
            sh.update(f0=f0, n=f1 - f0, off=off / FPS)
            sh["s"], sh["e"] = f0 / FPS, f1 / FPS
            off += f1 - f0
            saida.append(sh)
        self.shots = saida
        self.duracao = off / FPS

    def tempo(self, take, t):
        """Converte o tempo de uma tomada para o tempo final do video."""
        for sh in self.shots:
            if sh["take"] == take and t < sh["e"]:
                return sh["off"] + max(0.0, t - sh["s"])
        ultimo = [s for s in self.shots if s["take"] == take][-1]
        return ultimo["off"] + ultimo["e"] - ultimo["s"]

    def inicio_de(self, take, palavra, n=0):
        return self.tempo(take, self._acha(self.tokens[take], palavra, n)["s"])

    def fim_de(self, take, palavra, n=0):
        return self.tempo(take, self._acha(self.tokens[take], palavra, n)["e"])

    def fim_take(self, take):
        ultimo = [s for s in self.shots if s["take"] == take][-1]
        return ultimo["off"] + ultimo["e"] - ultimo["s"]

    # ------------------------------------------------------------ rostos e zoom
    def rostos(self):
        pasta = os.path.join(self.t, "rosto_frames")
        cache = os.path.join(self.t, "rostos.json")
        dados = json.load(open(cache)) if os.path.exists(cache) else {}
        faltam = [t for t in self.p.TOMADAS if t not in dados]
        if not faltam:
            return dados
        os.makedirs(pasta, exist_ok=True)

        def extrai(take):
            rodar(["ffmpeg", "-y", "-v", "error", "-i", os.path.join(self.p.SDR, f"IMG_{take}.mov"),
                   "-vf", "fps=2,scale=360:-2", "-q:v", "4", os.path.join(pasta, f"{take}_%04d.jpg")])

        with ThreadPoolExecutor(5) as ex:
            list(ex.map(extrai, faltam))
        saida = subprocess.run(["swift", os.path.join(AQUI, "rostos.swift"), pasta],
                               check=True, capture_output=True, text=True).stdout
        for t in faltam:
            dados[t] = []
        for ln in saida.splitlines():
            nome, cx, cy, h = ln.split()
            take, idx = nome[:-4].split("_")
            dados[take].append([(int(idx) - 1) / 2, float(cx), float(cy), float(h)])
        json.dump(dados, open(cache, "w"))
        shutil.rmtree(pasta)
        return dados

    def definir_zoom(self):
        faces = self.rostos()
        ciclo = 0
        primeira = getattr(self.p, "PRIMEIRA_DO_CORPO", None)
        for sh in self.shots:
            if sh["take"] == primeira and ciclo >= 0 and not getattr(self, "_corpo", False):
                # Os ganchos alternativos reaproveitam os mesmos planos do corpo.
                ciclo, self._corpo = 0, True
            pontos = [p for p in faces.get(sh["take"], []) if sh["s"] - 0.5 <= p[0] <= sh["e"] + 0.5]
            if pontos:
                sh["cx"], sh["cy"], sh["fh"] = [float(np.median([p[i] for p in pontos])) for i in (1, 2, 3)]
            else:
                sh["cx"], sh["cy"], sh["fh"] = 0.5, 0.3, 0.1
            if sh["wide"]:
                seq = [1.0, 1.0, 1.12]
            elif sh["fh"] > 0.17:
                seq = [1.0, 1.14]
            else:
                seq = [1.0, 1.22, 1.08, 1.32]
            # O rosto nunca passa de 26% da altura, para nao cortar a cabeca no zoom.
            sh["z"] = max(1.0, min(seq[ciclo % len(seq)], 0.26 / max(sh["fh"], 0.01)))
            fixo = self.p.TOMADAS[sh["take"]].get("zoom")
            if fixo:
                sh["z"] = fixo
            ciclo += 1

    # ------------------------------------------------------------ render da base
    def adicionar_cena(self, t0, t1, arquivo, ini=0.0, foco=(0.5, 0.5), z=1.04, pb=False, vel=1.0, recorte=None, ate=None, puro=False):
        """Registra um corte para o banco. ate = ultimo segundo utilizavel da origem: a cena desacelera para nao passar dele."""
        self.cenas.append(dict(t0=t0, t1=t1, arquivo=arquivo, ini=ini, foco=foco, z=z, pb=pb, vel=vel, recorte=recorte, ate=ate, puro=puro))

    def _ajustar_cenas(self):
        """Alinha ao frame, tira sobreposicao e garante tempo minimo da pessoa entre duas cenas de apoio."""
        ordem = sorted(self.cenas, key=lambda c: c["t0"])
        total = round(self.duracao * FPS)
        for c in ordem:
            c["f0"], c["f1"] = round(c["t0"] * FPS), min(round(c["t1"] * FPS), total)
        for x, y in zip(ordem, ordem[1:]):
            x["f1"] = min(x["f1"], y["f0"])
        minimo = round(getattr(self.p, "MIN_FALA", 0.4) * FPS)
        teto = round(getattr(self.p, "MAX_CENA", 99) * FPS)
        # Efeito de vídeo conta como fala, porque a pessoa continua na tela. Prova pode ficar mais tempo.
        apoios = [c for c in ordem if not c["puro"]]
        puros = [c for c in ordem if c["puro"]]
        eh_prova = lambda c: os.path.basename(c["arquivo"]).startswith("prova_")
        for c in apoios:
            if not eh_prova(c):
                c["f1"] = min(c["f1"], c["f0"] + teto)
        for x, y in zip(apoios, apoios[1:]):
            espaco = y["f0"] - x["f1"]
            # So emenda se a cena continuar curta; se nao couber, o aviso de falas curtas pede ajuste no plano.
            if 0 < espaco < minimo and (eh_prova(x) or x["f1"] - x["f0"] + espaco <= teto):
                entre = [c for c in puros if c["f0"] < y["f0"] and c["f1"] > x["f1"]]
                x["f1"] = entre[0]["f0"] if entre else y["f0"]
        self.cenas = [c for c in ordem if c["f1"] - c["f0"] >= 5]
        apoios = [c for c in self.cenas if not c["puro"]]
        fala = [y["f0"] - x["f1"] for x, y in zip(apoios, apoios[1:]) if y["f0"] > x["f1"]]
        self.menor_fala = min(fala) / FPS if fala else 0
        self.falas_curtas = [(round(x["f1"] / FPS, 1), round((y["f0"] - x["f1"]) / FPS, 2))
                             for x, y in zip(apoios, apoios[1:]) if 0 < y["f0"] - x["f1"] < minimo]
        return self.cenas

    def _dim(self, arquivo):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json", arquivo],
                           check=True, capture_output=True, text=True).stdout
        j = json.loads(r)
        st = j["streams"][0]
        w, h = st["width"], st["height"]
        for sd in st.get("side_data_list", []):
            if abs(sd.get("rotation", 0)) == 90:
                w, h = h, w
        return w, h, float(j.get("format", {}).get("duration", 0) or 0)

    def trecho_fala(self, t0, t1, saida):
        """Gera so a imagem da fala entre t0 e t1, com o enquadramento dos planos, para receber um efeito."""
        pasta = os.path.join(self.t, "planos2")
        os.makedirs(pasta, exist_ok=True)
        f0, f1 = round(t0 * FPS), round(t1 * FPS)
        partes = []
        for sh in self.shots:
            ini_f = round(sh["off"] * FPS)
            a, b = max(f0, ini_f), min(f1, ini_f + sh["n"])
            if a < b:
                arq = os.path.join(pasta, f"f_{sh['take']}_{sh['f0'] + a - ini_f}_{b - a}_{sh['z']:.3f}_{int(sh['bw'])}.mp4")
                if not os.path.exists(arq):
                    self._render_fala(sh, sh["f0"] + a - ini_f, b - a, arq)
                partes.append(arq)
        lista = saida + ".txt"
        with open(lista, "w") as f:
            for a in partes:
                f.write(f"file '{a}'\n")
        rodar(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", saida])
        os.remove(lista)

    def _render_cena(self, c, saida):
        n = c["f1"] - c["f0"]
        if c["puro"]:
            # Clipe ja pronto (efeito de vídeo): so garante tamanho, ritmo e duracao.
            tmp = saida + ".tmp.mp4"
            rodar(["ffmpeg", "-y", "-v", "error", "-i", c["arquivo"], "-frames:v", str(n), "-vf",
                   f"scale={W}:{H},fps={FPS},tpad=stop_mode=clone:stop_duration=2,setsar=1,format=yuv420p", "-an",
                   "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-colorspace", "bt709",
                   "-color_primaries", "bt709", "-color_trc", "bt709", "-video_track_timescale", "30000", tmp])
            os.rename(tmp, saida)
            return
        dur = n / FPS
        w, h, total = self._dim(c["arquivo"])
        imagem = c["arquivo"].lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        vf = []
        if c["recorte"]:
            x0, y0, x1, y1 = c["recorte"]
            vf.append(f"crop=iw*{x1-x0}:ih*{y1-y0}:iw*{x0}:ih*{y0}")
            w, h = w * (x1 - x0), h * (y1 - y0)
        vel = c["vel"]
        if c["ate"]:
            vel = min(vel, (c["ate"] - c["ini"]) / dur)
        if not imagem and total:
            vel = min(vel, max((total - c["ini"]) / dur, 0.2))
            vf.append(f"setpts=PTS/{vel:.4f}")
        vf.append(f"fps={FPS}")
        k = max(W / w, H / h)
        sw, sh = w * k, h * k
        zz = f"({c['z']}*(1+0.07*t/{dur:.3f})+0.15*exp(-t*13))"
        fx, fy = c["foco"]
        vf.append(f"scale=w='trunc({sw:.1f}*{zz}/2)*2':h='trunc({sh:.1f}*{zz}/2)*2':eval=frame:flags=bicubic")
        vf.append(f"crop={W}:{H}:x='clip({fx}*iw-{W/2},0,iw-{W})':y='clip({fy}*ih-{H/2},0,ih-{H})',setsar=1")
        if c["pb"]:
            vf.append("hue=s=0,eq=contrast=1.14")
        # Dois quadros borrados na entrada dao o efeito de chicote do corte.
        vf.append("gblur=sigma=26:enable='lt(n,1)',gblur=sigma=11:enable='eq(n,1)',format=yuv420p")
        ent = ["-loop", "1", "-framerate", str(FPS), "-i", c["arquivo"]] if imagem else ["-ss", f"{c['ini']:.3f}", "-i", c["arquivo"]]
        tmp = saida + ".tmp.mp4"
        rodar(["ffmpeg", "-y", "-v", "error", *ent, "-frames:v", str(n), "-vf", ",".join(vf), "-an", "-r", str(FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-colorspace", "bt709",
               "-color_primaries", "bt709", "-color_trc", "bt709", "-video_track_timescale", "30000", tmp])
        os.rename(tmp, saida)

    def rosto_em(self, t):
        """Onde o rosto está no vídeo final em t: (centro x, centro y, altura), em pixels."""
        for sh in self.shots:
            if sh["off"] <= t < sh["off"] + sh["n"] / FPS:
                z = sh["z"]
                cx = sh["cx"] * W * z - min(max(sh["cx"] * W * z - W / 2, 0), W * z - W)
                cy = sh["cy"] * H * z - min(max(sh["cy"] * H * z - 0.36 * H, 0), H * z - H)
                return cx, cy, sh["fh"] * H * z
        return W / 2, 0.36 * H, 0.15 * H

    def _render_fala(self, sh, f0, n, saida):
        dur = n / FPS
        z = f"({sh['z']}*(1+0.035*t/{dur:.3f}))"
        vf = (
            f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame:flags=bicubic,"
            f"crop={W}:{H}:x='clip({sh['cx']:.4f}*iw-{W/2},0,iw-{W})':"
            f"y='clip({sh['cy']:.4f}*ih-{0.36*H},0,ih-{H})',setsar=1"
        )
        if sh["bw"]:
            vf += ",hue=s=0,eq=contrast=1.12"
        vf += ",format=yuv420p"
        tmp = saida + ".tmp.mp4"
        rodar(["ffmpeg", "-y", "-v", "error", "-ss", f"{f0/FPS:.4f}",
               "-i", os.path.join(self.p.SDR, f"IMG_{sh['take']}.mov"),
               "-frames:v", str(n), "-vf", vf, "-an", "-r", str(FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-video_track_timescale", "30000", tmp])
        os.rename(tmp, saida)

    def render_base(self):
        pasta = os.path.join(self.t, "planos2")
        os.makedirs(pasta, exist_ok=True)
        cenas = self._ajustar_cenas()
        trabalhos = []
        cob = sum(c["f1"] - c["f0"] for c in cenas if not c["puro"])
        for sh in self.shots:
            ini_f = round(sh["off"] * FPS)
            fim_f = ini_f + sh["n"]
            cortes = [(max(c["f0"], ini_f), min(c["f1"], fim_f)) for c in cenas if c["f0"] < fim_f and c["f1"] > ini_f]
            cur = ini_f
            for a, b in cortes:
                if a > cur:
                    trabalhos.append(("fala", cur, sh, sh["f0"] + cur - ini_f, a - cur))
                cur = b
            if cur < fim_f:
                trabalhos.append(("fala", cur, sh, sh["f0"] + cur - ini_f, fim_f - cur))
        for c in cenas:
            trabalhos.append(("cena", c["f0"], c, 0, c["f1"] - c["f0"]))
        trabalhos.sort(key=lambda x: x[1])

        def um(tr):
            tipo, _pos, obj, f0, n = tr
            if tipo == "fala":
                nome = f"f_{obj['take']}_{f0}_{n}_{obj['z']:.3f}_{int(obj['bw'])}.mp4"
                saida = os.path.join(pasta, nome)
                if not os.path.exists(saida):
                    self._render_fala(obj, f0, n, saida)
            else:
                base = json.dumps({k: obj[k] for k in ("arquivo", "ini", "foco", "z", "pb", "vel", "recorte", "ate", "puro")}, sort_keys=True)
                if obj["arquivo"].lower().endswith((".jpg", ".jpeg")) and os.path.getsize(obj["arquivo"]) < 5_000_000:
                    # Provas sao regeneradas a cada execucao: a chave segue o conteudo da imagem.
                    base += hashlib.md5(open(obj["arquivo"], "rb").read()).hexdigest()
                chave = hashlib.md5(base.encode() + str(n).encode()).hexdigest()[:12]
                saida = os.path.join(pasta, f"c_{chave}.mp4")
                if not os.path.exists(saida):
                    self._render_cena(obj, saida)
            return saida

        with ThreadPoolExecutor(6) as ex:
            arquivos = list(ex.map(um, trabalhos))
        lista = os.path.join(self.t, "lista.txt")
        with open(lista, "w") as f:
            for a in arquivos:
                f.write(f"file '{a}'\n")
        base = os.path.join(self.t, "base.mp4")
        rodar(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", base])
        self.cobertura = cob / round(self.duracao * FPS)
        self.n_planos = len(trabalhos)
        return base

    # ------------------------------------------------------------ legendas
    def _emocao(self, take):
        for bloco in self.p.BLOCOS:
            if take in bloco["takes"]:
                return bloco["emocao"]
        return "virada"

    def _tema(self):
        return TEMAS[getattr(self.p, "TEMA_LEGENDA", "classica")]

    def _grupos(self):
        """Define o estilo de cada bloco de palavras e funde contexto + destaque nas empilhadas."""
        grupos, contador = [], {}
        for take, toks in self.tokens.items():
            emo = self._emocao(take)
            cor, rota = ROTA[emo]
            rota = self._tema().get("rota", {}).get(emo, rota)
            anterior = None
            for chunk in self._blocos(toks):
                if not any(w["dest"] for w in chunk):
                    item = {"take": take, "palavras": chunk, "estilo": "base", "cor": cor, "ctx": 0}
                    grupos.append(item)
                    anterior = item
                    continue
                chave = (take, norm(chunk[0]["txt"]))
                estilo = self.p.ESTILO_FORCADO.get(chave)
                if not estilo:
                    estilo = rota[contador.get(emo, 0) % len(rota)]
                    contador[emo] = contador.get(emo, 0) + 1
                if estilo == "empilhada" and anterior and len(anterior["palavras"]) <= 3 \
                        and chunk[0]["s"] - anterior["palavras"][-1]["e"] < 0.35:
                    grupos.remove(anterior)
                    grupos.append({"take": take, "palavras": anterior["palavras"] + chunk, "estilo": estilo,
                                   "cor": cor, "ctx": len(anterior["palavras"])})
                else:
                    if estilo == "empilhada":
                        estilo = "impacto"
                    grupos.append({"take": take, "palavras": chunk, "estilo": estilo, "cor": cor, "ctx": 0})
                anterior = None
        return grupos

    @staticmethod
    def _ajustar(texto, chave, maximo, largura=960):
        """Devolve (linhas, tamanho) para o texto caber na largura, em ate duas linhas."""
        fonte = FONTES_LEG[chave]

        def mede(t, tam):
            return ImageFont.truetype(fonte, tam).getlength(t)

        pal = texto.split()
        opcoes = [[texto]]
        for i in range(1, len(pal)):
            opcoes.append([" ".join(pal[:i]), " ".join(pal[i:])])
        melhor = None
        for ops in opcoes:
            tam = maximo
            while tam > 40 and max(mede(l, tam) for l in ops) > largura:
                tam -= 4
            if melhor is None or tam > melhor[1] + (6 if len(ops) > 1 else 0):
                melhor = (ops, tam)
        return melhor

    def legendas(self):
        eventos = []
        for g in self._grupos():
            take, chunk = g["take"], g["palavras"]
            fim_g = self.tempo(take, chunk[-1]["e"]) + 0.12
            ini_g = self.tempo(take, chunk[0]["s"])
            if g["estilo"] == "caixa":
                eventos.append({"a": ini_g, "b": fim_g, "g": g, "i": len(chunk) - 1, "primeiro": True})
                continue
            for i, w in enumerate(chunk):
                a = self.tempo(take, w["s"])
                b = self.tempo(take, chunk[i + 1]["s"]) if i + 1 < len(chunk) else fim_g
                if b - a < 1 / FPS:
                    continue
                eventos.append({"a": a, "b": b, "g": g, "i": i, "primeiro": a == ini_g})
        eventos.sort(key=lambda e: e["a"])
        linhas = [
            "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            self._estilo_base(),
            "Style: A,Anton,150,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,1,0,1,5,5,5,50,50,0,1",
            "Style: M,Excalifont,110,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,5,4,5,50,50,0,1",
            "Style: E,Instrument Serif,128,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,0,1,0,0,100,100,0,0,1,3,5,5,50,50,0,1",
            "Style: C,Montserrat Black,70,&H00101010,&H00101010,&H0000D5FF,&H00000000,0,0,0,0,100,100,0,0,3,18,0,5,50,50,0,1",
            "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for k, ev in enumerate(eventos):
            a, b = ev["a"], ev["b"]
            if k + 1 < len(eventos):
                b = min(b, eventos[k + 1]["a"])
            if b - a < 1 / FPS or any(x <= a < y for x, y in self.sem_legenda):
                continue
            estilo, texto = self._texto_evento(ev, a)
            linhas.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},{estilo},,0,0,0,,{texto}")
        caminho = os.path.join(self.t, "legendas.ass")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas))
        return caminho

    def _estilo_base(self):
        tema = self._tema().get("base")
        if tema == "faixa":
            return "Style: L,Montserrat Black,60,&H00101010,&H00101010,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,3,16,0,5,70,70,0,1"
        if tema == "gigante":
            return "Style: L,Anton,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,1,0,1,5,4,5,70,70,0,1"
        return "Style: L,Montserrat Black,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,3,4,5,70,70,0,1"

    def _base_tematica(self, tema, limpo, i, cor, pos, primeiro):
        """Texto corrido dos temas: karaoke pinta a palavra atual, faixa é caixa branca, gigante vem em Anton."""
        pop = "\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)" if primeiro else ""
        if tema == "faixa":
            return "L", "{" + pos + "\\frz-1" + pop + "}" + " ".join(limpo[: i + 1])
        partes = []
        for j, t in enumerate(limpo):
            vis = t.upper() if tema == "gigante" else t
            if j == i:
                partes.append("{\\alpha&H00&\\c" + cor + "}" + vis)
            else:
                partes.append("{\\alpha" + ("&H00&" if j < i else "&H70&") + "\\c&HFFFFFF&}" + vis)
        return "L", "{" + pos + pop + "}" + " ".join(partes)

    def _texto_evento(self, ev, a):
        g, i, primeiro = ev["g"], ev["i"], ev["primeiro"]
        chunk, est, (cor, caixa, sobre) = g["palavras"], g["estilo"], CORES[g["cor"]]
        limpo = [w["txt"].rstrip(",.") for w in chunk]
        y = self._y_legenda(a, est)
        pos = f"\\an5\\pos({W//2},{y})"
        pop = "\\fscx130\\fscy130\\t(0,110,\\fscx100\\fscy100)" if primeiro else ""
        tema_base = self._tema().get("base")
        if est == "base" and tema_base:
            return self._base_tematica(tema_base, limpo, i, cor, pos, primeiro)
        if est == "base":
            pop = "\\fscx74\\fscy74\\t(0,90,\\fscx100\\fscy100)" if primeiro else ""
            partes = []
            for j, t in enumerate(limpo):
                ativa = "\\alpha&H00&\\c&HFFFFFF&" if j <= i else "\\alpha&H70&\\c&HFFFFFF&"
                partes.append("{" + ativa + "}" + t)
            return "L", "{" + pos + pop + "}" + " ".join(partes)
        if est == "caixa":
            texto = " ".join(limpo).upper()
            ops, tam = self._ajustar(texto, "L", 84, 900)
            return "C", "{" + pos + f"\\frz-2\\fs{tam}\\c{sobre}\\3c{caixa}" + pop + "}" + "\\N".join(ops)
        chave = {"impacto": "A", "manuscrita": "M", "elegante": "E", "empilhada": "A"}[est]
        ctx = g["ctx"]
        foco = limpo[ctx:]
        vis = [t.upper() for t in foco] if chave == "A" else foco
        ops, tam = self._ajustar(" ".join(vis), chave, {"A": 178, "M": 122, "E": 138}[chave])
        extra = "\\frz-3" if est == "manuscrita" else ""
        saida, idx = [], ctx
        # Palavras do contexto ficam pequenas por cima, como nas empilhadas dos modelos.
        if ctx:
            topo = []
            for j in range(ctx):
                al = "&H00&" if j <= i else "&HA0&"
                topo.append("{\\fnMontserrat Black\\fs54\\c&HFFFFFF&\\alpha" + al + "\\bord3\\b0}" + limpo[j])
            saida.append(" ".join(topo))
        for linha in ops:
            parts = []
            for t in linha.split():
                al = "&H00&" if idx <= i else "&HFF&"
                parts.append("{" + f"\\fs{tam}\\c{cor}\\alpha{al}" + "}" + t)
                idx += 1
            saida.append(" ".join(parts))
        return chave, "{" + pos + extra + pop + "}" + "\\N".join(saida)

    def _blocos(self, toks):
        """Agrupa ate 3 palavras e deixa cada destaque sozinho no seu bloco."""
        blocos, atual = [], []
        for idx, t in enumerate(toks):
            atual.append(t)
            tam = sum(len(x["txt"]) for x in atual)
            prox = toks[idx + 1] if idx + 1 < len(toks) else None
            muda_destaque = prox is not None and prox["dest"] != t["dest"]
            destaque_segue = prox is not None and t["dest"] and prox["dest"]
            cheio = tam >= 15 or len(atual) >= 3
            if t["fim_frase"] or muda_destaque or (cheio and not (destaque_segue and tam < 22 and len(atual) < 3)):
                blocos.append(atual)
                atual = []
        if atual:
            blocos.append(atual)
        return blocos

    def _y_legenda(self, t, estilo="base"):
        for a, b, y in self.cap_y:
            if a <= t < b:
                return y
        y = self.p.LEGENDA_Y if estilo == "base" else self.p.LEGENDA_Y - 50
        return self._fora_do_rosto(t, y, 45 if estilo == "base" else 95)

    def _fora_do_rosto(self, t, y, meia):
        """Legenda centrada em y com meia altura 'meia'. Se o rosto do plano está nessa altura (plano fechado, rosto
        baixo), desce para baixo do queixo. Em cena de banco sem a pessoa, fica onde está."""
        if any(c["t0"] <= t < c["t1"] and not c["puro"] for c in self.cenas):
            return y
        _, cy, fh = self.rosto_em(t)
        olhos, queixo = cy - 0.15 * fh, cy + 0.55 * fh
        if y + meia > olhos and y - meia < queixo:
            return int(min(queixo + meia + 30, 1700))
        return y

    # ------------------------------------------------------------ audio
    def audio(self):
        ref = {}

        def carrega(take):
            bruto = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", os.path.join(self.p.CRU, self.p.CRU_NOMES.get(take, f"IMG_{take}.MOV")),
                 "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                check=True, capture_output=True).stdout
            ref[take] = np.frombuffer(bruto, dtype=np.int16) / 32768.0

        with ThreadPoolExecutor(5) as ex:
            list(ex.map(carrega, self.p.TOMADAS))
        total = round(self.duracao * SR)
        voz = np.zeros(total + SR)
        for sh in self.shots:
            ini = round(sh["f0"] / FPS * SR)
            n = round(sh["n"] / FPS * SR)
            trecho = ref[sh["take"]][ini:ini + n].copy()
            fade = min(192, len(trecho) // 2)
            trecho[:fade] *= np.linspace(0, 1, fade)
            trecho[-fade:] *= np.linspace(1, 0, fade)
            pos = round(sh["off"] * SR)
            voz[pos:pos + len(trecho)] += trecho
        voz = voz[:total]
        voz_wav = os.path.join(self.t, "voz_crua.wav")
        sons.grava(voz_wav, voz)
        limpa = os.path.join(self.t, "voz.raw")
        rodar(["ffmpeg", "-y", "-v", "error", "-i", voz_wav, "-af",
               "highpass=f=85,equalizer=f=3200:t=q:w=1.2:g=2,"
               "acompressor=threshold=-22dB:ratio=3:attack=6:release=90:makeup=3dB",
               "-f", "f64le", "-ac", "1", limpa])
        voz = np.fromfile(limpa, dtype=np.float64)[:total]
        voz = voz / (np.sqrt(np.mean(voz ** 2)) + 1e-9) * 10 ** (-20 / 20)
        for take, cfg in self.p.TOMADAS.items():
            if cfg.get("igualar"):
                planos = [sh for sh in self.shots if sh["take"] == take]
                igualar_voz(voz, min(sh["off"] for sh in planos), max(sh["off"] + sh["n"] / FPS for sh in planos),
                            0.0 if cfg["igualar"] is True else cfg["igualar"])
        for take, de, ate in getattr(self.p, "DISTORCER", []):
            distorcer_trecho(voz, self.inicio_de(take, de), self.fim_de(take, ate))

        # Trilha composta por blocos de emocao, com ganho proprio em cada bloco.
        trilha = self._carregar_trilha(total)
        hop = 960
        n = total // hop
        e = np.sqrt(np.mean(voz[: n * hop].reshape(n, hop) ** 2, axis=1))
        tem_voz = np.convolve((e > 10 ** (-38 / 20)).astype(float), np.ones(8) / 8, mode="same")
        ganho = np.interp(np.arange(total), np.arange(n) * hop, 1 - 0.38 * tem_voz)
        trilha *= ganho
        fim_fade = int(1.2 * SR)
        trilha[-fim_fade:] *= np.linspace(1, 0, fim_fade)
        mix = voz + trilha

        lib = sons.carregar()
        for t, nome, extra in self.sons:
            s = lib[nome] * 10 ** ((GANHO_SOM[nome] + extra) / 20)
            pos = int(max(t, 0) * SR)
            fim = min(pos + len(s), total)
            if pos < total:
                mix[pos:fim] += s[: fim - pos]
        mix_wav = os.path.join(self.t, "mix.wav")
        sons.grava(mix_wav, np.clip(mix, -1, 1))
        final = os.path.join(self.t, "audio_final.wav")
        # Ganho fixo com limitador: o loudnorm dinamico achatava a oscilacao entre os blocos.
        medida = subprocess.run(["ffmpeg", "-nostats", "-i", mix_wav, "-af", "ebur128", "-f", "null", "-"],
                                capture_output=True, text=True).stderr
        lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", medida)[-1])
        rodar(["ffmpeg", "-y", "-v", "error", "-i", mix_wav, "-af",
               f"volume={-15 - lufs:.2f}dB,alimiter=limit=0.84:attack=5:release=60:level=disabled",
               "-ar", str(SR), "-ac", "2", final])
        return final

    def _carregar_trilha(self, total):
        """Monta a trilha: cada bloco tem sua faixa, seu nivel e um cruzamento curto para o proximo."""
        cruz = int(0.45 * SR)
        saida = np.zeros(total)
        for i, bl in enumerate(self.secoes):
            a = int(bl["t0"] * SR)
            b = min(int(bl["t1"] * SR) + cruz, total)
            n = b - a
            arq = os.path.join(self.p.MUSICAS, self.p.FAIXAS[bl["faixa"]])
            bruto = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(bl["ini"]), "-t", f"{n / SR + 0.1:.3f}", "-i", arq,
                                    "-ac", "1", "-ar", str(SR), "-f", "f64le", "-"], check=True, capture_output=True).stdout
            x = np.frombuffer(bruto, dtype=np.float64)[:n].copy()
            x = x / (np.sqrt(np.mean(x ** 2)) + 1e-9) * 10 ** ((self.p.TRILHA_RMS + bl["ganho"]) / 20)
            if i:
                x[:cruz] *= np.linspace(0, 1, cruz)
            if b < total:
                x[-cruz:] *= np.linspace(1, 0, cruz)
            saida[a:a + len(x)] += x
        return saida

    # ------------------------------------------------------------ composicao
    def compor(self, base, ass, audio, saida):
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", base, "-i", audio]
        # A base passa por fps e settb, e cada sobreposicao entra com tpad transparente:
        # so com setpts o FFmpeg atrasava a entrada em ate 1 s e pulava a animacao.
        filtros, atual = [f"[0:v]fps={FPS},settb=1/{FPS}[b0]"], "b0"
        for i, ov in enumerate(self.overlays):
            cmd += ["-i", ov["arquivo"]]
            ent = i + 2
            filtros.append(f"[{ent}:v]format=rgba,fps={FPS},settb=1/{FPS},tpad=start_duration={round(ov['t'] * FPS) / FPS:.4f}:color=black@0[o{i}]")
            filtros.append(f"[{atual}][o{i}]overlay=x={ov['x']}:y={ov['y']}:eof_action=pass:format=auto[v{i}]")
            atual = f"v{i}"
        vel = getattr(self.p, "VELOCIDADE", 1.0)
        acelera = f",setpts=PTS/{vel},fps={FPS}" if vel != 1.0 else ""
        filtros.append(f"[{atual}]ass={os.path.basename(ass)}:fontsdir=fontes{acelera},format=yuv420p[fim]")
        fontes = os.path.join(self.t, "fontes")
        shutil.rmtree(fontes, ignore_errors=True)
        shutil.copytree(os.path.join(AQUI, "fontes"), fontes)
        for arg in ["-filter_complex", ";".join(filtros), "-map", "[fim]", "-map", "1:a", *(["-af", f"atempo={vel}"] if vel != 1.0 else []),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    # Sem isso o arquivo saía com transferência e primárias "desconhecidas" e o player clareava a imagem.
                    "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-map_metadata", "-1",
                    "-movflags", "+faststart", "-fflags", "+bitexact", saida]:
            cmd.append(arg)
        rodar(cmd, cwd=self.t)


def _ts(t):
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ---------------------------------------------------------------- grafismos
def _fonte(tam):
    return ImageFont.truetype(FONTE_BLACK, tam)


def _sombra(img, raio=18, opac=120, desloc=8):
    pad = raio * 2
    tela = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2 + desloc), (0, 0, 0, 0))
    alpha = img.getchannel("A").point(lambda v: v * opac // 255)
    preta = Image.new("RGBA", img.size, (0, 0, 0, 255))
    preta.putalpha(alpha)
    tela.paste(preta, (pad, pad + desloc), preta)
    tela = tela.filter(ImageFilter.GaussianBlur(raio))
    tela.alpha_composite(img, (pad, pad))
    return tela


def _emoji(ch, tam):
    f = ImageFont.truetype(EMOJI, 160)
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((20, 20), ch, font=f, embedded_color=True)
    return im.crop(im.getbbox()).resize((tam, tam), Image.LANCZOS)


def pilula(texto, cor=VERDE, simbolo=None, tam=58, seta=False):
    """simbolo: 'x', 'ok' ou um emoji."""
    f = _fonte(tam)
    tw = int(f.getlength(texto))
    icone = int(tam * 1.15) if simbolo else 0
    gap = 22 if simbolo else 0
    larg = tw + icone + gap + 76
    alt = int(tam * 2.05)
    im = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, larg - 1, alt - 1), radius=alt // 2 if alt < 130 else 40, fill=cor)
    x = 38
    if simbolo in ("x", "ok"):
        yc = alt // 2
        r = icone // 2
        d.ellipse((x, yc - r, x + icone, yc + r), fill=BRANCO)
        tr = max(7, tam // 7)
        if simbolo == "x":
            m = r // 2 + 2
            cx = x + r
            d.line((cx - m, yc - m, cx + m, yc + m), fill=cor, width=tr)
            d.line((cx - m, yc + m, cx + m, yc - m), fill=cor, width=tr)
        else:
            cx = x + r
            d.line((cx - r // 2, yc, cx - r // 8, yc + r // 2 - 2, cx + r // 2 + 2, yc - r // 2 + 2),
                   fill=cor, width=tr, joint="curve")
    elif simbolo:
        im.alpha_composite(_emoji(simbolo, icone), (x, (alt - icone) // 2))
    if simbolo:
        x += icone + gap
    caixa = f.getbbox(texto)
    d.text((x, (alt - (caixa[3] - caixa[1])) // 2 - caixa[1]), texto, font=f, fill=BRANCO)
    return _sombra(im)


def grafismo(texto, estilo="pilula", cor=VERDE, simbolo=None, tam=58):
    """Formatos de grafismo. 'pilula' é o original; os demais dão variedade entre os criativos."""
    if estilo == "pilula":
        return pilula(texto, cor=cor, simbolo=simbolo, tam=tam)
    if estilo == "contorno":
        f = _fonte(tam)
        icone = int(tam * 0.72) if simbolo in ("x", "ok") else 0
        recuo = icone + 22 if icone else 0
        larg = int(f.getlength(texto)) + recuo + 84
        alt = int(tam * 2.1)
        im = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((3, 3, larg - 4, alt - 4), radius=20, fill=(14, 14, 16, 225), outline=cor, width=7)
        caixa = f.getbbox(texto)
        y = (alt - (caixa[3] - caixa[1])) // 2 - caixa[1]
        if simbolo == "x":
            topo, fim = (alt - icone) // 2, (alt + icone) // 2
            d.line((42, topo, 42 + icone, fim), fill=cor, width=max(7, tam // 6))
            d.line((42, fim, 42 + icone, topo), fill=cor, width=max(7, tam // 6))
        elif simbolo == "ok":
            topo = (alt - icone) // 2
            d.line((42, topo + icone * 0.55, 42 + icone * 0.38, topo + icone, 42 + icone, topo + icone * 0.12),
                   fill=cor, width=max(7, tam // 6), joint="curve")
        d.text((42 + recuo, y), texto, font=f, fill=BRANCO)
        return _sombra(im)
    chave = "M" if estilo == "manuscrito" else "A"
    corpo = int(tam * (2.15 if chave == "M" else 1.55))
    f = ImageFont.truetype(FONTES_LEG[chave], corpo)
    while f.getlength(texto) > 900 and corpo > 40:
        corpo -= 4
        f = ImageFont.truetype(FONTES_LEG[chave], corpo)
    tw = int(f.getlength(texto))
    caixa = f.getbbox(texto)
    th = caixa[3] - caixa[1]
    larg, alt = tw + 70, th + 74
    im = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if estilo == "etiqueta":
        d.rectangle((0, 8, larg - 1, alt - 9), fill=cor)
        d.text((35, (alt - th) // 2 - caixa[1]), texto, font=f, fill=BRANCO)
        return _sombra(im.rotate(2.5, expand=True, resample=Image.BICUBIC))
    if estilo == "marcador":
        # Traço de marca-texto irregular atrás do texto.
        passos = np.linspace(0, larg - 1, 9)
        topo = [(x, 14 + 8 * np.sin(i * 1.7)) for i, x in enumerate(passos)]
        base = [(x, alt - 14 + 8 * np.cos(i * 2.1)) for i, x in enumerate(passos)]
        d.polygon(topo + base[::-1], fill=cor)
        d.text((35, (alt - th) // 2 - caixa[1]), texto, font=f, fill=BRANCO)
        return _sombra(im.rotate(-1.5, expand=True, resample=Image.BICUBIC))
    # manuscrito: letra à mão com sublinhado na cor.
    d.text((35, 6 - caixa[1]), texto, font=f, fill=BRANCO, stroke_width=7, stroke_fill=(0, 0, 0, 255))
    y = th + 24
    d.line([(x, y + 6 * np.sin(x / 38)) for x in range(30, larg - 30, 8)], fill=cor, width=13, joint="curve")
    return _sombra(im)


def _sem_pecas_soltas(img):
    """Tira brilhos e estrelinhas soltos, que viravam quadrados brancos com a borda do recorte."""
    lado = 128
    a = np.array(img.getchannel("A").resize((lado, lado), Image.BILINEAR)) > 40
    rotulo = np.zeros((lado, lado), dtype=int)
    tamanhos = {}
    atual = 0
    for y0, x0 in zip(*np.nonzero(a)):
        if rotulo[y0, x0]:
            continue
        atual += 1
        pilha, n = [(y0, x0)], 0
        rotulo[y0, x0] = atual
        while pilha:
            y, x = pilha.pop()
            n += 1
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < lado and 0 <= xx < lado and a[yy, xx] and not rotulo[yy, xx]:
                    rotulo[yy, xx] = atual
                    pilha.append((yy, xx))
        tamanhos[atual] = n
    maior = max(tamanhos.values())
    fica = np.isin(rotulo, [k for k, v in tamanhos.items() if v >= maior * 0.12])
    mascara = Image.fromarray((fica * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).resize(img.size, Image.NEAREST)
    saida = img.copy()
    saida.putalpha(Image.fromarray(np.minimum(np.array(img.getchannel("A")), np.array(mascara))))
    return saida


def sticker(nome, tam=170):
    """Sticker 3D da pasta stickers (Noto Emoji, licença aberta) com borda branca recortada."""
    img = _sem_pecas_soltas(Image.open(os.path.join(AQUI, "stickers", f"{nome}.png")).convert("RGBA"))
    img = img.crop(img.getbbox())
    img.thumbnail((tam, tam), Image.LANCZOS)
    borda = max(8, tam // 30)
    tela = Image.new("RGBA", (img.width + borda * 2 + 4, img.height + borda * 2 + 4), (0, 0, 0, 0))
    tela.paste(img, (borda + 2, borda + 2), img)
    mascara = tela.getchannel("A").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(borda * 2 - 1)).filter(ImageFilter.GaussianBlur(1))
    fundo = Image.new("RGBA", tela.size, (255, 255, 255, 255))
    fundo.putalpha(mascara)
    fundo.alpha_composite(tela)
    return _sombra(fundo, raio=12, opac=110, desloc=6)


def animar_sticker(img, dur, saida, lado=1):
    """Entra girando com salto, balança leve e sai encolhendo. Gera MOV com transparência."""
    n = max(int(dur * FPS), 10)
    lado_tela = int(max(img.size) * 1.42) // 2 * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{lado_tela}x{lado_tela}",
         "-r", str(FPS), "-i", "-", "-c:v", "qtrle", saida], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for f in range(n):
        p = f / FPS
        if f < 8:
            u = (f + 1) / 8
            esc = 0.2 + 1.0 * u + 0.18 * np.sin(u * np.pi)
            giro = -22 * lado * (1 - u)
        else:
            esc = 1 + 0.025 * np.sin(p * 2 * np.pi * 1.3)
            giro = 6 * lado * np.sin(p * 2 * np.pi * 0.9)
        if f >= n - 4:
            esc *= (n - f) / 4
        atual = img.resize((max(round(img.width * esc), 2), max(round(img.height * esc), 2)), Image.BILINEAR).rotate(giro, expand=True, resample=Image.BILINEAR)
        quadro = Image.new("RGBA", (lado_tela, lado_tela), (0, 0, 0, 0))
        quadro.alpha_composite(atual, ((lado_tela - atual.width) // 2, (lado_tela - atual.height) // 2)) if atual.width <= lado_tela and atual.height <= lado_tela else quadro.alpha_composite(atual.crop(((atual.width - lado_tela) // 2, (atual.height - lado_tela) // 2, (atual.width + lado_tela) // 2, (atual.height + lado_tela) // 2)), (0, 0))
        proc.stdin.write(quadro.tobytes())
    proc.stdin.close()
    proc.wait()
    return lado_tela


def card_imagem(caminho_ou_img, largura, raio=28, borda=0):
    img = caminho_ou_img if isinstance(caminho_ou_img, Image.Image) else Image.open(caminho_ou_img)
    img = img.convert("RGBA")
    alt = round(img.height * largura / img.width)
    img = img.resize((largura, alt), Image.LANCZOS)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, largura - 1, alt - 1), radius=raio, fill=255)
    img.putalpha(mask)
    return _sombra(img)


def fundo_marca():
    """Fundo escuro com brilho verde da marca."""
    yy, xx = np.mgrid[0:H, 0:W]
    brilho = np.exp(-(((xx - W / 2) / 760) ** 2 + ((yy - 760) / 900) ** 2))
    tela = np.stack([10 + 8 * brilho, 13 + 92 * brilho, 12 + 46 * brilho, np.full_like(brilho, 255)], axis=-1)
    return Image.fromarray(tela.astype(np.uint8), "RGBA")


def tela_prova(caminho, saida, largura=960, alt_max=1240, topo=190):
    """Print de prova grande sobre um fundo escuro com brilho verde da marca."""
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    fundo = fundo_marca()
    k = min(largura / img.width, alt_max / img.height)
    card = card_imagem(img, round(img.width * k))
    y = topo if card.height > 500 else 420
    fundo.alpha_composite(card, ((W - card.width) // 2, y))
    fundo.convert("RGB").save(saida, quality=94)
    return saida, y + card.height


def retrato(caminho, saida, maior=2600):
    """Grava a imagem ja na orientacao correta (o HEIC do iPhone vem com EXIF)."""
    if caminho.lower().endswith(".heic"):
        # O Pillow deste Mac nao le HEIC; o sips converte e mantem a orientacao no EXIF.
        rodar(["sips", "-s", "format", "jpeg", caminho, "--out", saida])
        caminho = saida
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    img.thumbnail((maior, maior), Image.LANCZOS)
    img.save(saida, quality=94)
    return saida


def recorte_quadro(video, t, x0, y0, x1, y1, trabalho, nome):
    png = os.path.join(trabalho, f"q_{nome}.png")
    rodar(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1",
           "-vf", f"crop=iw*{x1-x0}:ih*{y1-y0}:iw*{x0}:ih*{y0}", png])
    return png


def etiqueta_manuscrita(texto, tam=112, cor=BRANCO, rot=-5):
    f = ImageFont.truetype(FONTES_LEG["M"], tam)
    caixa = f.getbbox(texto)
    im = Image.new("RGBA", (caixa[2] + 60, caixa[3] + 60), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((30, 20), texto, font=f, fill=cor, stroke_width=4, stroke_fill=(0, 0, 0, 255))
    return _sombra(im.rotate(-rot, expand=True, resample=Image.BICUBIC), raio=10)


def tile_emoji(ch, tam=190):
    im = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, tam - 1, tam - 1), radius=38, fill=BRANCO)
    e = _emoji(ch, int(tam * 0.68))
    im.alpha_composite(e, ((tam - e.width) // 2, (tam - e.height) // 2))
    return _sombra(im, raio=14)


def janela_erro(largura=760, linhas=("Ops! Algo", "deu errado"), sub="Esta página saiu do ar."):
    alt = 330
    im = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, largura - 1, alt - 1), radius=30, fill=BRANCO)
    d.rounded_rectangle((0, 0, largura - 1, 70), radius=30, fill=(232, 234, 238, 255))
    d.rectangle((0, 40, largura - 1, 70), fill=(232, 234, 238, 255))
    for i, c in enumerate([(240, 82, 82, 255), (245, 190, 60, 255), (70, 195, 100, 255)]):
        d.ellipse((28 + i * 34, 24, 50 + i * 34, 46), fill=c)
    im.alpha_composite(_emoji("⚠️", 110), (46, 142))
    d.text((186, 124), linhas[0], font=_fonte(52), fill=(30, 30, 35, 255))
    d.text((186, 184), linhas[1], font=_fonte(52), fill=(30, 30, 35, 255))
    d.text((186, 256), sub, font=_fonte(30), fill=(110, 112, 120, 255))
    return _sombra(im)


def animar(img, dur, saida, balanco=False):
    """Entrada com salto, saida com fade. Gera MOV com transparencia."""
    n = max(int(dur * FPS), 8)
    w, h = img.size
    extra = 40 if balanco else 0
    cw, ch = (w + 40) // 2 * 2, (h + 40 + extra) // 2 * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{cw}x{ch}",
         "-r", str(FPS), "-i", "-", "-c:v", "qtrle", saida],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for f in range(n):
        if f < 5:
            esc = 0.55 + (1.07 - 0.55) * (f + 1) / 5
        elif f < 9:
            esc = 1.07 - 0.07 * (f - 4) / 4
        else:
            esc = 1.0
        opac = 1.0
        if f >= n - 4:
            opac = (n - f) / 5
        if f < 3:
            opac = (f + 1) / 3
        quadro = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        fw, fh = round(w * esc), round(h * esc)
        atual = img if esc == 1.0 else img.resize((fw, fh), Image.BILINEAR)
        if opac < 1:
            atual = atual.copy()
            a = atual.getchannel("A").point(lambda v, o=opac: int(v * o))
            atual.putalpha(a)
        dy = int(16 * np.sin(f / FPS * 2 * np.pi * 1.6)) if balanco and f >= 9 else 0
        quadro.alpha_composite(atual, ((cw - fw) // 2, (ch - fh) // 2 + dy))
        proc.stdin.write(quadro.tobytes())
    proc.stdin.close()
    proc.wait()
    return cw, ch


def clipe_card(video, ini, dur, x0, y0, x1, y1, largura, saida, trabalho, raio=26):
    """Recorta uma regiao de outro video e devolve como card arredondado com fade."""
    area_w = x1 - x0
    area_h = y1 - y0
    with_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", video], check=True, capture_output=True, text=True).stdout.strip().split(",")
    vw, vh = int(with_probe[0]), int(with_probe[1])
    alt = round(vh * area_h * largura / (vw * area_w)) // 2 * 2
    mask = Image.new("L", (largura, alt), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, largura - 1, alt - 1), radius=raio, fill=255)
    m = os.path.join(trabalho, f"mask_{largura}_{alt}.png")
    mask.save(m)
    filtro = (
        f"[0:v]crop=iw*{area_w}:ih*{area_h}:iw*{x0}:ih*{y0},scale={largura}:{alt},fps={FPS},format=rgba[a];"
        f"[1:v]format=gray[m];[a][m]alphamerge,fade=in:st=0:d=0.12:alpha=1,"
        f"fade=out:st={max(dur-0.12,0):.3f}:d=0.12:alpha=1[o]"
    )
    rodar(["ffmpeg", "-y", "-v", "error", "-ss", str(ini), "-t", f"{dur:.3f}", "-i", video,
           "-loop", "1", "-t", f"{dur:.3f}", "-i", m, "-filter_complex", filtro, "-map", "[o]",
           "-an", "-c:v", "qtrle", saida])
    return largura, alt


def clipe_tela_cheia(video, ini, dur, x_centro, altura_rel, saida):
    """B-roll em tela cheia, usando so a area acima da legenda queimada do video de origem."""
    filtro = (
        f"crop=ih*{altura_rel}*9/16:ih*{altura_rel}:"
        f"clip(iw*{x_centro}-ih*{altura_rel}*9/32\\,0\\,iw-ih*{altura_rel}*9/16):0,"
        f"scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1,format=rgba,"
        f"fade=in:st=0:d=0.08:alpha=1,fade=out:st={max(dur-0.08,0):.3f}:d=0.08:alpha=1"
    )
    rodar(["ffmpeg", "-y", "-v", "error", "-ss", str(ini), "-t", f"{dur:.3f}", "-i", video,
           "-vf", filtro, "-an", "-c:v", "qtrle", saida])
