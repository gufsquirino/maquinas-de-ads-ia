"""Peças animadas quadro a quadro, desenhadas em PIL.

Cada peça é uma função desenhar(t) -> imagem RGBA do tamanho da peça, com t em segundos desde a entrada.
renderizar() grava um MOV com transparência (qtrle), como os grafismos do motor.

  lista(...)        itens entram cada um na sua palavra; marca X (risca o texto) ou check
  contador(...)     número contando até o valor falado, com pulinho ao pousar
  notificacao(...)  celular sobe e as notificações caem uma por palavra
  polaroide(...)    foto real em moldura de polaroide, cai girando e assenta torta
  etiqueta(...)     papel com fita, frase se escrevendo à mão palavra por palavra, marca-texto no destaque

Regras: entra na palavra (tempos vindos do motor), uma ideia por vez, nada sobre o rosto
(posição decidida em ad.peca), valor em dinheiro só em print real (as notificações não mostram valor).
"""
import math
import os
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
FPS = 30
F_BLACK = os.path.join(AQUI, "fontes", "Montserrat-Black.ttf")
F_BOLD = os.path.join(AQUI, "fontes", "Montserrat-ExtraBold.ttf")
F_MAO = os.path.join(AQUI, "fontes", "Excalifont-Regular.ttf")

CARTAO = (255, 253, 252, 255)
TINTA = (38, 33, 46, 255)
CINZA = (128, 122, 138, 255)
VERDE = (22, 197, 94, 255)
VERDE_ESCURO = (10, 120, 60, 255)
VERMELHO = (229, 40, 62, 255)
AMARELO_MT = (255, 222, 60, 200)
LINHA = (228, 222, 236, 255)


# ------------------------------------------------------------------ curvas
def _u(t, ini, dur):
    return min(max((t - ini) / dur, 0.0), 1.0) if dur > 0 else float(t >= ini)


def back_out(u, forca=2.0):
    c1 = 1.70158 * forca / 2 + 0.6
    c3 = c1 + 1
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


def cubic_out(u):
    return 1 - (1 - u) ** 3


def power3_in(u):
    return u ** 3


def power4_in(u):
    return u ** 4


def fonte(caminho, tam):
    return ImageFont.truetype(caminho, tam)


def sombra(img, raio=22, opac=110, desloc=10):
    pad = raio * 2
    tela = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2 + desloc), (0, 0, 0, 0))
    a = img.getchannel("A").point(lambda v: v * opac // 255)
    preta = Image.new("RGBA", img.size, (0, 0, 0, 255))
    preta.putalpha(a)
    tela.paste(preta, (pad, pad + desloc), preta)
    tela = tela.filter(ImageFilter.GaussianBlur(raio))
    tela.alpha_composite(img, (pad, pad))
    return tela, pad


def opacidade(img, o):
    if o >= 0.999:
        return img
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * max(o, 0))))
    return img


def colar(base, camada, x, y, o=1.0, rot=0.0):
    """Cola camada com centro de giro no meio, em coordenadas do canto superior esquerdo sem giro."""
    if o <= 0.001:
        return
    if rot:
        w, h = camada.size
        camada = camada.rotate(-rot, expand=True, resample=Image.BICUBIC)
        x -= (camada.width - w) / 2
        y -= (camada.height - h) / 2
    camada = opacidade(camada, o)
    base.alpha_composite(camada, (int(round(x)), int(round(y))))


def entrada_saida(t, dur, entra=0.35, sai=0.25, dy_in=64, dy_out=-28, forca=2.0):
    """(opacidade, deslocamento y) da peça inteira: sobe com mola na entrada, some subindo na saída."""
    ui = _u(t, 0, entra)
    o = min(1.0, ui * 2.5)
    dy = dy_in * (1 - back_out(ui, forca))
    uo = _u(t, dur - sai, sai)
    if uo > 0:
        o *= 1 - power3_in(uo)
        dy += dy_out * power3_in(uo)
    return o, dy


def texto_rico(draw, xy, texto, f, cor, cor_destaque):
    """Escreve 'Piores *dicas*': o trecho entre asteriscos vai na cor de destaque."""
    x, y = xy
    for i, parte in enumerate(texto.split("*")):
        if parte:
            draw.text((x, y), parte, font=f, fill=cor_destaque if i % 2 else cor)
            x += draw.textlength(parte, font=f)
    return x


def largura_rica(texto, f):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    return d.textlength(texto.replace("*", ""), font=f)


# ------------------------------------------------------------------ marcas desenhadas
def bolinha(tam, tipo, progresso_traco):
    """Círculo verde com check ou vermelho com X; o traço se desenha de 0 a 1."""
    esc = 4
    s = tam * esc
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), fill=VERDE if tipo == "check" else VERMELHO)
    lw = int(s * 0.13)
    if tipo == "check":
        pts = [(0.25, 0.53), (0.43, 0.71), (0.76, 0.32)]
        segs = [(pts[0], pts[1]), (pts[1], pts[2])]
    else:
        segs = [((0.3, 0.3), (0.7, 0.7)), ((0.7, 0.3), (0.3, 0.7))]
    total = sum(math.dist(a, b) for a, b in segs)
    resta = progresso_traco * total
    for a, b in segs:
        comp = math.dist(a, b)
        if resta <= 0:
            break
        f = min(1.0, resta / comp)
        fim = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        d.line([(a[0] * s, a[1] * s), (fim[0] * s, fim[1] * s)], fill=(255, 255, 255, 255), width=lw)
        for p in (a, fim):
            d.ellipse((p[0] * s - lw / 2, p[1] * s - lw / 2, p[0] * s + lw / 2, p[1] * s + lw / 2), fill=(255, 255, 255, 255))
        resta -= comp
    return img.resize((tam, tam), Image.LANCZOS)


# ------------------------------------------------------------------ 1. lista
def lista(titulo, itens, dur, marca="x", largura=760, atraso_marca=0.25, tam=46):
    """itens: [(texto, t)] com t em segundos desde a entrada da peça. marca: 'x' (risca) ou 'check'.
    Também aceita (texto, t, marca) para misturar."""
    f_tit, f_item = fonte(F_BLACK, 44), fonte(F_BOLD, tam)
    linha_h, topo, pad = 104, (96 if titulo else 34), 44
    alt = topo + linha_h * len(itens) + 26
    base_cartao = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    ImageDraw.Draw(base_cartao).rounded_rectangle((0, 0, largura - 1, alt - 1), radius=34, fill=CARTAO)
    cartao, sp = sombra(base_cartao)
    W, H = cartao.size[0], cartao.size[1] + 70

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur)
        peca = cartao.copy()
        d = ImageDraw.Draw(peca)
        if titulo:
            tx = sp + (largura - largura_rica(titulo, f_tit)) / 2
            texto_rico(d, (tx, sp + 26), titulo, f_tit, TINTA, VERMELHO if marca == "x" else VERDE_ESCURO)
        for i, item in enumerate(itens):
            texto, ti = item[0], item[1]
            tipo = item[2] if len(item) > 2 else marca
            ui = _u(t, ti, 0.3)
            if ui <= 0:
                continue
            y0 = sp + topo + i * linha_h
            camada = Image.new("RGBA", (largura, linha_h), (0, 0, 0, 0))
            dc = ImageDraw.Draw(camada)
            for x in range(pad, largura - pad, 22):
                dc.line([(x, 1), (x + 11, 1)], fill=LINHA, width=3)
            tw = dc.textlength(texto, font=f_item)
            ty = (linha_h - tam) // 2 - 6
            dc.text((pad, ty), texto, font=f_item, fill=TINTA)
            um = _u(t, ti + atraso_marca, 0.18)
            if tipo == "x" and um > 0:
                ur = cubic_out(_u(t, ti + atraso_marca + 0.05, 0.22))
                yr = linha_h // 2
                dc.rounded_rectangle((pad - 8, yr - 4, pad - 8 + (tw + 16) * ur, yr + 4), radius=4, fill=VERMELHO)
            if um > 0:
                b = bolinha(64, tipo, cubic_out(_u(t, ti + atraso_marca + 0.05, 0.25)))
                k = 0.2 + 0.8 * power4_in(um) if um < 1 else 1.0
                bs = max(2, int(64 * k))
                b = b.resize((bs, bs), Image.LANCZOS)
                camada.alpha_composite(opacidade(b, um), (largura - pad - 32 - bs // 2, linha_h // 2 - bs // 2 - int(26 * (1 - power4_in(um)))))
            colar(peca, camada, sp - 40 * (1 - back_out(ui)), y0, o=min(1, ui * 2.5))
        colar(quadro, peca, 0, 35 + dy, o=o)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 2. contador
def formatar(v, casas=0):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def contador(valor, dur, sufixo="", rotulo="", inicio=0.15, conta=0.9, largura=640, casas=0):
    f_num, f_suf, f_rot = fonte(F_BLACK, 150), fonte(F_BLACK, 58), fonte(F_BOLD, 40)
    alt = 250 if rotulo else 200
    base_cartao = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    ImageDraw.Draw(base_cartao).rounded_rectangle((0, 0, largura - 1, alt - 1), radius=36, fill=CARTAO)
    cartao, sp = sombra(base_cartao)
    W, H = cartao.size[0], cartao.size[1] + 90
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w_final = d0.textlength(formatar(valor, casas), font=f_num) + d0.textlength(sufixo, font=f_suf) + 14

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur)
        uc = _u(t, inicio, conta)
        v = valor * cubic_out(uc)
        pouso = _u(t, inicio + conta, 0.37)
        if 0 < pouso < 1:
            dy += -14 * math.sin(math.pi * pouso)
        peca = cartao.copy()
        d = ImageDraw.Draw(peca)
        num = formatar(v, casas)
        x = sp + (largura - w_final) / 2
        w_max = d.textlength(formatar(valor, casas), font=f_num)
        d.text((x + w_max - d.textlength(num, font=f_num), sp + 8), num, font=f_num, fill=VERDE_ESCURO)
        x += w_max + 14
        d.text((x, sp + 86), sufixo, font=f_suf, fill=TINTA)
        if rotulo:
            rw = d.textlength(rotulo, font=f_rot)
            d.text((sp + (largura - rw) / 2, sp + 186), rotulo, font=f_rot, fill=CINZA)
        colar(quadro, peca, 0, 45 + dy, o=o)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 3. notificação
def _sacola(tam):
    s = tam * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), fill=VERDE)
    d.rounded_rectangle((s * 0.27, s * 0.36, s * 0.73, s * 0.76), radius=s * 0.06, fill=(255, 255, 255, 255))
    d.arc((s * 0.36, s * 0.2, s * 0.64, s * 0.5), 180, 360, fill=(255, 255, 255, 255), width=int(s * 0.06))
    return img.resize((tam, tam), Image.LANCZOS)


def notificacao(notas, dur, titulo="Hoje", largura=380, altura=660):
    """notas: [(titulo, linha, t)]. Cada nota cai no topo da lista e empurra as anteriores para baixo."""
    f_hora, f_tit, f_t, f_l = fonte(F_BLACK, 64), fonte(F_BOLD, 28), fonte(F_BLACK, 30), fonte(F_BOLD, 22)
    corpo = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dc = ImageDraw.Draw(corpo)
    dc.rounded_rectangle((0, 0, largura - 1, altura - 1), radius=64, fill=(18, 18, 22, 255))
    tela = Image.new("RGBA", (largura - 28, altura - 28), (0, 0, 0, 0))
    grad = Image.new("RGBA", tela.size)
    gd = ImageDraw.Draw(grad)
    for yy in range(tela.height):
        k = yy / tela.height
        gd.line([(0, yy), (tela.width, yy)], fill=(int(12 + 20 * k), int(70 + 60 * (1 - k)), int(44 + 20 * (1 - k)), 255))
    m = Image.new("L", tela.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tela.width - 1, tela.height - 1), radius=52, fill=255)
    tela.paste(grad, (0, 0), m)
    dt = ImageDraw.Draw(tela)
    dt.rounded_rectangle((tela.width / 2 - 62, 16, tela.width / 2 + 62, 50), radius=17, fill=(0, 0, 0, 255))
    hw = dt.textlength("09:41", font=f_hora)
    dt.text(((tela.width - hw) / 2, 92), "09:41", font=f_hora, fill=(255, 255, 255, 235))
    tw = dt.textlength(titulo, font=f_tit)
    dt.text(((tela.width - tw) / 2, 172), titulo, font=f_tit, fill=(255, 255, 255, 200))
    corpo.alpha_composite(tela, (14, 14))
    celular, sp = sombra(corpo, raio=26, opac=140)
    nota_w, nota_h, gap, topo = largura - 64, 104, 14, 14 + 230
    icone = _sacola(62)
    check = bolinha(34, "check", 1.0)
    W, H = celular.size[0], celular.size[1] + 140

    def cartao_nota(tit, linha):
        c = Image.new("RGBA", (nota_w, nota_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(c)
        d.rounded_rectangle((0, 0, nota_w - 1, nota_h - 1), radius=26, fill=(255, 255, 255, 240))
        c.alpha_composite(icone, (18, (nota_h - 62) // 2))
        ft = f_t
        tam_t = 30
        while d.textlength(tit, font=ft) > nota_w - 96 - 64 and tam_t > 18:
            tam_t -= 1
            ft = fonte(F_BLACK, tam_t)
        d.text((96, 18 + (30 - tam_t) // 2), tit, font=ft, fill=TINTA)
        d.text((96, 58), linha, font=f_l, fill=CINZA)
        c.alpha_composite(check, (nota_w - 52, (nota_h - 34) // 2))
        return c

    cartoes = [cartao_nota(a, b) for a, b, _ in notas]

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur, entra=0.5, dy_in=120, dy_out=60, forca=1.5)
        peca = celular.copy()
        chegadas = [ti for _, _, ti in notas]
        for i, c in enumerate(cartoes):
            ui = _u(t, chegadas[i], 0.3)
            if ui <= 0:
                continue
            depois = sum(cubic_out(_u(t, tj, 0.3)) for tj in chegadas[i + 1:])
            y = sp + topo + depois * (nota_h + gap) - 80 * (1 - back_out(ui))
            if y + nota_h > sp + altura - 30:
                continue
            colar(peca, c, sp + 32, y, o=min(1, ui * 3))
        colar(quadro, peca, 0, 70 + dy, o=o)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 4. polaroide
def polaroide(foto, legenda, dur, largura=440, rot=-6, foco=(0.5, 0.5), zoom=1.0):
    """foto: caminho ou Image. Recorte quadrado no 'foco' (frações). Cai girando e assenta em 'rot' graus."""
    img = foto if isinstance(foto, Image.Image) else Image.open(foto)
    img = img.convert("RGB")
    lado = min(img.size) / zoom
    cx, cy = img.width * foco[0], img.height * foco[1]
    x0 = min(max(cx - lado / 2, 0), img.width - lado)
    y0 = min(max(cy - lado / 2, 0), img.height - lado)
    borda = 22
    fw = largura - 2 * borda
    quadrada = img.crop((x0, y0, x0 + lado, y0 + lado)).resize((fw, fw), Image.LANCZOS)
    alt = borda + fw + 100
    moldura = Image.new("RGBA", (largura, alt), (250, 249, 245, 255))
    moldura.paste(quadrada, (borda, borda))
    d = ImageDraw.Draw(moldura)
    tam_leg = 50
    while d.textlength(legenda, font=fonte(F_MAO, tam_leg)) > largura - 50 and tam_leg > 26:
        tam_leg -= 2
    f = fonte(F_MAO, tam_leg)
    lw = d.textlength(legenda, font=f)
    d.text(((largura - lw) / 2, borda + fw + 22), legenda, font=f, fill=TINTA)
    pecaimg, sp = sombra(moldura, raio=20, opac=130)
    diag = int(math.hypot(*pecaimg.size)) + 40
    W, H = diag, diag + 120

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ui = _u(t, 0, 0.45)
        k = back_out(ui, 1.7)
        r = rot * 2.6 + (rot - rot * 2.6) * k
        dy = -120 * (1 - k)
        o = min(1, ui * 3)
        uo = _u(t, dur - 0.25, 0.25)
        if uo > 0:
            o *= 1 - power3_in(uo)
            dy -= 40 * power3_in(uo)
        colar(quadro, pecaimg, (W - pecaimg.width) / 2, 120 + (H - 120 - pecaimg.height) / 2 + dy, o=o, rot=r)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 5. etiqueta de papel
def etiqueta(palavras, dur, destaque=(), largura=760, tam=66, rot=-2.5):
    """palavras: [(palavra, t)]. A frase se escreve à mão, uma palavra no seu tempo; palavras em 'destaque'
    ganham marca-texto amarelo 0,15 s depois de aparecer. Quebra em linhas pela largura."""
    f = fonte(F_MAO, tam)
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pad, esp, lh = 46, d0.textlength(" ", font=f), int(tam * 1.32)
    linhas, atual, w_atual = [], [], 0
    for p, ti in palavras:
        w = d0.textlength(p, font=f)
        if atual and w_atual + esp + w > largura - 2 * pad:
            linhas.append(atual)
            atual, w_atual = [], 0
        atual.append((p, ti, w))
        w_atual += (esp if w_atual else 0) + w
    linhas.append(atual)
    alt = pad + lh * len(linhas) + pad - 10
    papel = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    ImageDraw.Draw(papel).rounded_rectangle((0, 0, largura - 1, alt - 1), radius=10, fill=(255, 252, 240, 255))
    papel_s, sp = sombra(papel, raio=18, opac=110)
    fita = Image.new("RGBA", (170, 46), (190, 170, 240, 170))
    pos = []
    for li, ln in enumerate(linhas):
        total = sum(w for _, _, w in ln) + esp * (len(ln) - 1)
        x = (largura - total) / 2
        for p, ti, w in ln:
            pos.append((p, ti, x, pad - 8 + li * lh, w))
            x += w + esp
    W = int(math.hypot(papel_s.width, papel_s.height)) + 20
    H = papel_s.height + 120

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur, entra=0.35, dy_in=-50, forca=2.0)
        peca = papel_s.copy()
        d = ImageDraw.Draw(peca)
        for p, ti, x, y, w in pos:
            if p.strip("*,.!?") in destaque or p in destaque:
                um = cubic_out(_u(t, ti + 0.15, 0.3))
                if um > 0:
                    d.rounded_rectangle((sp + x - 8, sp + y + tam * 0.45, sp + x - 8 + (w + 16) * um, sp + y + tam * 1.12),
                                        radius=8, fill=AMARELO_MT)
        for p, ti, x, y, w in pos:
            up = _u(t, ti, 0.18)
            if up > 0:
                camada = Image.new("RGBA", (int(w + 20), int(lh + 20)), (0, 0, 0, 0))
                ImageDraw.Draw(camada).text((4, 4), p, font=f, fill=TINTA)
                colar(peca, camada, sp + x - 4, sp + y - 4 + 10 * (1 - cubic_out(up)), o=up)
        peca.alpha_composite(fita.rotate(4, expand=True, resample=Image.BICUBIC), (sp + largura // 2 - 88, max(0, sp - 26)))
        colar(quadro, peca, (W - peca.width) / 2, 60 + dy, o=o, rot=rot)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 6. balão de pergunta
def balao(palavras, dur, rotulo="PERGUNTA", largura=860, tam=50):
    """Pergunta de quem está fora da câmera: balão de conversa que se escreve palavra por palavra junto com a voz.
    palavras: [(palavra, t)]."""
    f, f_rot = fonte(F_BOLD, tam), fonte(F_BLACK, 26)
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pad, esp, lh = 40, d0.textlength(" ", font=f), int(tam * 1.3)
    linhas, atual, w_atual = [], [], 0
    for p, ti in palavras:
        w = d0.textlength(p, font=f)
        if atual and w_atual + esp + w > largura - 2 * pad:
            linhas.append(atual)
            atual, w_atual = [], 0
        atual.append((p, ti, w))
        w_atual += (esp if w_atual else 0) + w
    linhas.append(atual)
    topo = 66
    alt = topo + lh * len(linhas) + pad - 6
    corpo = Image.new("RGBA", (largura, alt + 34), (0, 0, 0, 0))
    dc = ImageDraw.Draw(corpo)
    dc.rounded_rectangle((0, 0, largura - 1, alt - 1), radius=40, fill=CARTAO)
    dc.polygon([(70, alt - 2), (130, alt - 2), (66, alt + 32)], fill=CARTAO)
    rw = dc.textlength(rotulo, font=f_rot)
    dc.rounded_rectangle((pad - 4, 20, pad + rw + 22, 56), radius=18, fill=VERDE)
    dc.text((pad + 9, 23), rotulo, font=f_rot, fill=(255, 255, 255, 255))
    balao_s, sp = sombra(corpo)
    pos = []
    for li, ln in enumerate(linhas):
        x = pad
        for p, ti, w in ln:
            pos.append((p, ti, x, topo + li * lh))
            x += w + esp
    W, H = balao_s.width, balao_s.height + 60

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur, entra=0.3, dy_in=-40)
        peca = balao_s.copy()
        d = ImageDraw.Draw(peca)
        for p, ti, x, y in pos:
            up = _u(t, ti, 0.12)
            if up > 0:
                cor = TINTA if up >= 1 else (TINTA[0], TINTA[1], TINTA[2], int(255 * up))
                d.text((sp + x, sp + y), p, font=f, fill=cor)
        colar(quadro, peca, 0, 30 + dy, o=o)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ 7. cartão de logo
def logo(imagem, nome, dur, largura=520, fundo_logo=None):
    """Marca citada na fala: cartão com o logo (ou só o nome, enquanto o logo não chega) que entra com mola.
    imagem: caminho, Image ou None. fundo_logo: cor do quadrado atrás do logo (para logo de fundo escuro)."""
    f = fonte(F_BLACK, 52)
    alt = 150
    lado = 112
    base = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((0, 0, largura - 1, alt - 1), radius=40, fill=CARTAO)
    x_txt = 36
    img = None
    if imagem is not None:
        img = imagem if isinstance(imagem, Image.Image) else Image.open(imagem)
        img = img.convert("RGBA")
    if img is not None and img.width > 2.5 * img.height:
        # Logo com o nome escrito (wordmark): ocupa o cartão inteiro, sem repetir o nome.
        img.thumbnail((largura - 80, alt - 56), Image.LANCZOS)
        base.alpha_composite(img, ((largura - img.width) // 2, (alt - img.height) // 2))
        nome = ""
        img = None
    if img is not None:
        img.thumbnail((lado, lado), Image.LANCZOS)
        q = Image.new("RGBA", (lado + 16, lado + 16), fundo_logo or (0, 0, 0, 0))
        m = Image.new("L", q.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, q.width - 1, q.height - 1), radius=26, fill=255)
        q.alpha_composite(img, ((q.width - img.width) // 2, (q.height - img.height) // 2))
        q.putalpha(Image.composite(q.getchannel("A"), Image.new("L", q.size, 0), m) if fundo_logo is None else m)
        base.alpha_composite(q, (18, (alt - q.height) // 2))
        x_txt = 18 + q.width + 22
    tam = 52
    while d.textlength(nome, font=f) > largura - x_txt - 30 and tam > 30:
        tam -= 2
        f = fonte(F_BLACK, tam)
    if nome:
        d.text((x_txt, (alt - tam) // 2 - 6), nome, font=f, fill=TINTA)
    cartao, sp = sombra(base)
    W, H = cartao.width, cartao.height + 80

    def desenhar(t):
        quadro = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o, dy = entrada_saida(t, dur, entra=0.35, dy_in=60)
        colar(quadro, cartao, 0, 40 + dy, o=o)
        return quadro

    return desenhar, (W, H)


# ------------------------------------------------------------------ gravação
def renderizar(desenhar, tamanho, dur, saida):
    w, h = (tamanho[0] + 1) // 2 * 2, (tamanho[1] + 1) // 2 * 2
    n = max(int(round(dur * FPS)), 2)
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
                             "-r", str(FPS), "-i", "-", "-c:v", "qtrle", saida], stdin=subprocess.PIPE)
    for f in range(n):
        q = desenhar(f / FPS)
        if q.size != (w, h):
            c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            c.alpha_composite(q, (0, 0))
            q = c
        proc.stdin.write(q.tobytes())
    proc.stdin.close()
    proc.wait()
    return w, h


# ------------------------------------------------------------------ na edição
def colocar(ed, pasta, nome, fabrica, t0, t1, y=None, x=None, legenda_y=1650, sons=(), y_min=560):
    """Põe a peça entre t0 e t1 do vídeo final (tempos do motor, já medidos na onda).
    fabrica(dur) devolve (desenhar, tamanho). Sem y, a peça fica logo abaixo do queixo (rosto livre) e
    nunca passa de y 1560; a legenda desce para legenda_y enquanto a peça está na tela.
    sons: [(t, nome, ganho)] em tempo do vídeo final."""
    t0 = max(t0, 0.0)
    dur = t1 - t0
    desenhar, tam = fabrica(dur)
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, f"peca_{nome}.mov")
    w, h = renderizar(desenhar, tam, dur, arq)
    if y is None:
        fundo = 0
        k = t0
        while k < t1:
            cx, cy, fh = ed.rosto_em(k)
            fundo = max(fundo, cy + 0.85 * fh)
            k += 0.2
        y = max(int(fundo), y_min)
        if y + h > 1640:
            # Não cabe abaixo do queixo: a peça diminui em vez de subir para o rosto.
            k = max((1640 - y) / h, 0.55)
            if k < 1:
                desenhar_orig = desenhar
                tam = (int(w * k), int(h * k))
                desenhar = lambda t, d=desenhar_orig, s=tam: d(t).resize(s, Image.LANCZOS)
                w, h = renderizar(desenhar, tam, dur, arq)
            y = min(y, 1640 - h)
    ed.overlays.append({"arquivo": arq, "t": t0, "x": (1080 - w) // 2 if x is None else x, "y": int(y)})
    if legenda_y:
        ed.cap_y.insert(0, (t0, t1, legenda_y))
    for t, nome_som, ganho in sons:
        ed.sons.append((t, nome_som, ganho))
    return y
