"""Biblioteca de sons sintetizados do zero: sem licenca de terceiros.

Uso: python3 sons.py <pasta_saida>
"""
import os
import sys
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(7)


def t(d):
    return np.arange(int(d * SR)) / SR


def banda(x, lo, hi):
    """Filtro passa-banda simples via FFT."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def norm(x, pico=0.9):
    return x / (np.max(np.abs(x)) + 1e-9) * pico


def env(d, a, r):
    """Ataque linear com decaimento exponencial."""
    tt = t(d)
    return np.minimum(tt / max(a, 1e-4), 1) * np.exp(-tt / r)


def whoosh(d=0.45, lo=300, hi=7000):
    n = int(d * SR)
    ruido = rng.standard_normal(n)
    blocos = 24
    saida = np.zeros(n)
    for i in range(blocos):
        a = int(i * n / blocos)
        b = int((i + 1) * n / blocos)
        p = i / (blocos - 1)
        centro = lo * (hi / lo) ** (np.sin(p * np.pi))
        trecho = banda(ruido[a:b], centro * 0.5, centro * 1.6)
        saida[a:b] = trecho * np.hanning(b - a)
    return norm(saida * np.sin(np.linspace(0, np.pi, n)) ** 1.5)


def pop():
    d = 0.14
    tt = t(d)
    freq = 900 * np.exp(-tt * 28) + 240
    fase = 2 * np.pi * np.cumsum(freq) / SR
    return norm(np.sin(fase) * env(d, 0.002, 0.035))


def tick():
    d = 0.06
    return norm(banda(rng.standard_normal(int(d * SR)), 1800, 9000) * env(d, 0.0005, 0.008), 0.7)


def ding():
    d = 0.9
    tt = t(d)
    s = sum(
        a * np.sin(2 * np.pi * f * tt) * np.exp(-tt / r)
        for f, a, r in [(1568, 1, 0.3), (3136, 0.45, 0.16), (4704, 0.2, 0.08)]
    )
    return norm(s * np.minimum(tt / 0.002, 1))


def sucesso():
    d = 0.7
    n = int(d * SR)
    s = np.zeros(n)
    for i, f in enumerate([784, 1047, 1319]):
        ini = int(i * 0.075 * SR)
        tt = np.arange(n - ini) / SR
        s[ini:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.2) * np.minimum(tt / 0.003, 1)
    return norm(s)


def erro():
    d = 0.34
    n = int(d * SR)
    tt = t(d)
    onda = np.sign(np.sin(2 * np.pi * 135 * tt)) + 0.5 * np.sign(np.sin(2 * np.pi * 142 * tt))
    onda = banda(onda, 90, 2200)
    e = np.ones(n)
    e[int(0.15 * SR) : int(0.19 * SR)] = 0.08
    e *= np.minimum(tt / 0.004, 1) * np.minimum((d - tt) / 0.03, 1)
    return norm(onda * e, 0.75)


def impacto():
    d = 1.1
    tt = t(d)
    freq = 110 * np.exp(-tt * 9) + 42
    fase = 2 * np.pi * np.cumsum(freq) / SR
    corpo = np.sin(fase) * np.exp(-tt / 0.3)
    ataque = banda(rng.standard_normal(len(tt)), 400, 5000) * np.exp(-tt / 0.03)
    return norm(corpo + 0.35 * ataque)


def caixa():
    """Moedas e campainha curta, para momentos de resultado."""
    d = 0.8
    n = int(d * SR)
    s = np.zeros(n)
    for ini, f in [(0.0, 2637), (0.05, 3136), (0.11, 3951), (0.17, 3520)]:
        i = int(ini * SR)
        tt = np.arange(n - i) / SR
        s[i:] += (np.sin(2 * np.pi * f * tt) + 0.4 * np.sin(2 * np.pi * f * 2.7 * tt)) * np.exp(-tt / 0.11)
    return norm(s)


def subida(d=1.1):
    n = int(d * SR)
    tt = t(d)
    freq = 180 * (1800 / 180) ** (tt / d)
    fase = 2 * np.pi * np.cumsum(freq) / SR
    tom = np.sin(fase) + 0.4 * np.sin(fase * 2.01)
    ruido = np.convolve(rng.standard_normal(n), np.ones(8) / 8, mode="same")
    return norm((tom * 0.5 + ruido * 0.5) * (tt / d) ** 2.2 * np.minimum((d - tt) / 0.01, 1))


def trilha(duracao, bpm=104):
    """Base discreta de pad com pulso grave em La menor. Fica por baixo da voz."""
    total = int(duracao * SR)
    batida = 60 / bpm
    acordes = [
        [110.0, 220.0, 261.63, 329.63],
        [87.31, 174.61, 261.63, 349.23],
        [130.81, 261.63, 329.63, 392.0],
        [98.0, 196.0, 293.66, 392.0],
    ]
    compasso = batida * 4
    n_c = int(compasso * SR)
    blocos = []
    for ac in acordes:
        tt = np.arange(n_c) / SR
        pad = sum(
            np.sin(2 * np.pi * f * tt + i)
            + 0.5 * np.sin(2 * np.pi * f * 1.004 * tt)
            + 0.18 * np.sin(2 * np.pi * f * 2 * tt)
            for i, f in enumerate(ac)
        )
        pad *= np.minimum(tt / 0.25, 1) * np.minimum((compasso - tt) / 0.25, 1)
        pulso = np.zeros(n_c)
        d_p = int(batida * SR)
        for k in range(4):
            i = k * d_p
            tp = np.arange(min(d_p, n_c - i)) / SR
            f0 = ac[0] / 2
            pulso[i : i + len(tp)] += np.sin(2 * np.pi * f0 * tp) * np.exp(-tp / 0.16)
        blocos.append(pad * 0.11 + pulso * 0.5)
    ciclo = np.concatenate(blocos)
    rep = int(np.ceil(total / len(ciclo)))
    return norm(np.tile(ciclo, rep)[:total], 0.8)


def moeda():
    """Duas batidas metálicas curtas, para fala de dinheiro."""
    saida = np.zeros(int(0.42 * SR))
    for ini, f in ((0.0, 1760), (0.075, 2637)):
        d = 0.42 - ini
        tt = t(d)
        som = sum(g * np.sin(2 * np.pi * f * k * tt) for k, g in ((1, 1), (2.76, 0.45), (5.4, 0.2))) * np.exp(-tt * 13)
        saida[int(ini * SR):int(ini * SR) + len(som)] += som
    return norm(saida)


def registradora():
    """Sino com a gaveta abrindo, para venda e lucro."""
    d = 0.75
    tt = t(d)
    sino = sum(g * np.sin(2 * np.pi * f * tt) for f, g in ((2093, 1), (3136, 0.7), (4186, 0.35))) * np.exp(-tt * 6)
    gaveta = np.zeros(len(tt))
    n = int(0.09 * SR)
    gaveta[:n] = banda(rng.standard_normal(n), 900, 5000) * np.hanning(n)
    return norm(sino * 0.8 + gaveta * 1.2)


def swoosh(d=0.3, lo=500, hi=5200):
    """Sopro que só sobe, mais limpo que o whoosh."""
    n = int(d * SR)
    ruido = rng.standard_normal(n)
    blocos = 18
    saida = np.zeros(n)
    for i in range(blocos):
        a, b = int(i * n / blocos), int((i + 1) * n / blocos)
        centro = lo * (hi / lo) ** (i / (blocos - 1))
        saida[a:b] = banda(ruido[a:b], centro * 0.6, centro * 1.5) * np.hanning(b - a)
    return norm(saida * np.linspace(0.25, 1, n) ** 1.4 * np.minimum(1, np.linspace(9, 0, n)))


def brilho():
    """Notas agudas subindo, para conquista e acerto."""
    saida = np.zeros(int(0.7 * SR))
    for i, f in enumerate((1568, 1976, 2349, 3136)):
        d = 0.7 - i * 0.07
        tt = t(d)
        som = np.sin(2 * np.pi * f * tt) * np.exp(-tt * 9)
        pos = int(i * 0.07 * SR)
        saida[pos:pos + len(som)] += som
    return norm(saida)


def vinil():
    """Disco arranhado, para fala negativa ou virada que corta o clima."""
    d = 0.36
    n = int(d * SR)
    ruido = rng.standard_normal(n)
    blocos = 16
    saida = np.zeros(n)
    for i in range(blocos):
        a, b = int(i * n / blocos), int((i + 1) * n / blocos)
        centro = 3200 * (0.12 ** (i / (blocos - 1)))
        saida[a:b] = banda(ruido[a:b], centro * 0.7, centro * 1.4) * np.hanning(b - a)
    return norm(saida)


def boing():
    """Mola curta, para sticker e momento leve."""
    d = 0.32
    tt = t(d)
    freq = 240 + 170 * np.sin(2 * np.pi * 15 * tt) * np.exp(-tt * 5)
    return norm(np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tt * 9))


def grava(caminho, x):
    x16 = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x16.tobytes())


BIBLIOTECA = {
    "whoosh": whoosh,
    "whoosh_curto": lambda: whoosh(0.25, 800, 9000),
    "pop": pop,
    "tick": tick,
    "ding": ding,
    "sucesso": sucesso,
    "erro": erro,
    "impacto": impacto,
    "caixa": caixa,
    "subida": subida,
    "moeda": moeda,
    "registradora": registradora,
    "swoosh": swoosh,
    "swoosh_grave": lambda: swoosh(0.42, 180, 2200),
    "brilho": brilho,
    "vinil": vinil,
    "boing": boing,
}


def carregar():
    return {nome: fn() for nome, fn in BIBLIOTECA.items()}


if __name__ == "__main__":
    pasta = sys.argv[1]
    os.makedirs(pasta, exist_ok=True)
    for nome, som in carregar().items():
        grava(os.path.join(pasta, nome + ".wav"), som)
    grava(os.path.join(pasta, "trilha_demo.wav"), trilha(12))
    print("sons gerados em", pasta)
