"""Base dos geradores de ad: cena, prova, pilula, efeito, parede de depoimentos e render.

Cada gerar_<id>.py so descreve o que aparece em cada fala e chama ad.rodar().
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import motor as m
import preparar_banco

# Efeitos de vídeo opcionais: aponte EDICAO_FX para uma pasta com scripts/fx.py e .venv (veja o README).
# Sem ela, efeito() vira uma pílula de texto e o render segue normal.
FX = os.environ.get("EDICAO_FX", "")
# Posições do paredão de prints (x, y). Os prints vêm de banco/provas, em ordem alfabética.
GRADE_PAREDE = [(-10, -20), (490, -30), (-10, 600), (490, 690), (-10, 1270), (490, 1400), (250, 240), (20, 900),
                (450, 1120), (40, 80), (440, 450), (230, 1000), (40, 560), (440, 1680)]
IMAGENS = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def provas_da_pasta(pasta):
    """Prints de depoimento em banco/provas. Use só prints com autorização e sem dados pessoais visíveis."""
    if not os.path.isdir(pasta):
        return []
    return sorted(n for n in os.listdir(pasta) if n.lower().endswith(IMAGENS))


class Ad:
    def __init__(self, p, pasta):
        self.p = p
        self.trab = os.path.join(p.SCRATCH, pasta)
        self.ed = m.Edicao(p, self.trab)
        self.ed.preparar()
        self.ed.definir_zoom()
        self.ov = os.path.join(self.trab, f"ov{p.GANCHO}")
        self.provas = getattr(p, "PROVAS", os.path.join(p.BANCO, "provas"))
        self.cont = 0
        self.sons_cena = []
        self._ultimo_grafismo = (-99, 0)

    def ini(self, take, palavra, n=0):
        return self.ed.inicio_de(take, palavra, n)

    def fim(self, take, palavra, n=0):
        return self.ed.fim_de(take, palavra, n)

    def fim_take(self, take):
        return self.ed.fim_take(take)

    def som(self, t, nome, extra=0):
        self.ed.sons.append((t, nome, extra))

    def grafico(self, img, t0, t1, y, x=None, sn=None):
        self.cont += 1
        arq = os.path.join(self.ov, f"{self.cont:03d}.mov")
        cw, _ = m.animar(img, t1 - t0 + 0.12, arq)
        self.ed.overlays.append({"arquivo": arq, "t": t0, "x": (m.W - cw) // 2 if x is None else x, "y": y})
        if sn:
            self.som(t0, sn)

    def pilula(self, texto, t0, t1, y=120, cor=m.VERDE, simbolo=None, sn="pop", tam=58):
        """GRAFISMOS no plano alterna os formatos. Grafismos em pilha, a menos de 3 s, mantêm o mesmo formato."""
        formatos = getattr(self.p, "GRAFISMOS", ["pilula"])
        ultimo_t, i = self._ultimo_grafismo
        if t0 - ultimo_t >= 3:
            i += 1
        self._ultimo_grafismo = (t0, i)
        # ZONA_SEGURA: o texto da pílula começa ~83 px abaixo do y; acima de 230 px a interface do Reels cobre.
        if getattr(self.p, "ZONA_SEGURA", False) and y < 400:
            y += 60
        self.grafico(m.grafismo(texto, formatos[i % len(formatos)], cor=cor, simbolo=simbolo, tam=tam), t0, t1, y, sn=sn)

    def sticker(self, nome, t0, t1=None, tam=170, sn="boing"):
        """Sticker pequeno na lateral, longe do rosto. Sem lugar com folga, não entra, e o render avisa."""
        rx, ry, rh = self.ed.rosto_em(t0)
        rw = rh * 0.85
        meio = tam * 0.62
        lugares = [(110, 500), (m.W - 110, 500), (110, 760), (m.W - 110, 760), (110, 1460), (m.W - 110, 1460)]
        if self.cont % 2:
            lugares = [lugares[i ^ 1] for i in range(len(lugares))]

        def folga(c):
            dx = abs(c[0] - rx) - rw * 0.75 - meio
            dy = abs(c[1] - ry) - rh * 0.75 - meio
            return max(dx, dy)

        cx, cy = next((c for c in lugares if folga(c) >= 60), max(lugares, key=folga))
        if folga((cx, cy)) < 20:
            print(f"AVISO sticker {nome} em {t0:.1f}s ficou de fora: sem folga do rosto", flush=True)
            return
        self.cont += 1
        arq = os.path.join(self.ov, f"{self.cont:03d}.mov")
        t1 = t0 + 1.4 if t1 is None else t1
        lado = m.animar_sticker(m.sticker(nome, tam), t1 - t0, arq, 1 if cx > m.W / 2 else -1)
        self.ed.overlays.append({"arquivo": arq, "t": t0, "x": int(cx - lado / 2), "y": int(cy - lado / 2)})
        if sn:
            self.som(t0, sn)

    def sons_por_palavra(self, intervalo=4.0):
        """Coloca moeda e registradora nas falas de dinheiro, sem repetir a menos de 'intervalo' segundos."""
        grana = {"dinheiro", "comissão", "reais", "lucro", "lucrativo", "faturamento", "renda", "pagos", "bolso", "cartão"}
        ultimo, n = -99, 0
        for take, toks in self.ed.tokens.items():
            for k in toks:
                if m.norm(k["txt"]) in {m.norm(w) for w in grana}:
                    t = self.ed.tempo(take, k["s"])
                    if t - ultimo >= intervalo:
                        self.som(t, "moeda" if n % 3 else "registradora")
                        ultimo, n = t, n + 1

    def nao(self, texto, t0, t1, y=120, tam=46):
        self.pilula(texto, t0, t1, y=y, cor=m.VERMELHO, simbolo="x", sn="erro", tam=tam)

    def sim(self, texto, t0, t1, y=120, tam=50):
        self.pilula(texto, t0, t1, y=y, simbolo="ok", sn="sucesso", tam=tam)

    def tempo(self, texto, t0, t1, y=120, tam=46):
        self.pilula(texto, t0, t1, y=y, simbolo="⏱️", sn="ding", tam=tam)

    def _arq(self, nome):
        return preparar_banco.sdr_ou_converte(nome, self.p.BANCO_SDR)

    def cena(self, a, b, clipe, ini_src=0.0, foco=(0.5, 0.5), z=1.04, pb=False, vel=1.0, sn="auto", ate=None):
        self.ed.adicionar_cena(a, b, clipe if os.path.isabs(clipe) else self._arq(clipe), ini_src, foco, z, pb, vel, ate=ate)
        if sn == "auto":
            self.sons_cena.append(a)

    def prova(self, nome, a, b, cap=1640, sn="whoosh", **kw):
        limpo = "".join(c for c in os.path.basename(nome) if c.isalnum())
        saida = os.path.join(self.trab, f"prova_{limpo}.jpg")
        _, base = m.tela_prova(os.path.join(self.provas, nome), saida, **kw)
        self.cena(a, b, saida, z=1.0, sn=None)
        self.ed.cap_y.append((a, b, max(cap, base + 110) if base < 1700 else cap))
        self.som(a, sn)

    def parede(self, a, b):
        """Cobre a tela só com prints, um a cada 0,3 s no mínimo, sem tela do sistema por baixo."""
        fundo = os.path.join(self.trab, "prova_parede.jpg")
        m.fundo_marca().convert("RGB").save(fundo, quality=94)
        self.cena(a, b, fundo, z=1.0, sn=None)
        def legivel(nome):
            # O macOS pode bloquear a leitura de um print (com.apple.macl): pula em vez de travar o render.
            try:
                with open(os.path.join(self.provas, nome), "rb") as f:
                    f.read(4)
                return True
            except PermissionError:
                print(f"AVISO parede: sem permissão para ler {nome}, ficou de fora", flush=True)
                return False

        disponiveis = [(n, *GRADE_PAREDE[i % len(GRADE_PAREDE)]) for i, n in enumerate(provas_da_pasta(self.provas)) if legivel(n)]
        lista = disponiveis[:min(len(disponiveis), int((b - a - 0.35) / 0.3))]
        passo = (b - a - 0.35) / len(lista)
        for i, (nome, x, y) in enumerate(lista):
            t0 = a + i * passo
            img = m.ImageOps.exif_transpose(m.Image.open(os.path.join(self.provas, nome)))
            self.grafico(m.card_imagem(img, 600, raio=22), t0, b + 0.02, y, x=x)
            self.som(t0, "caixa", -4)
        self.ed.cap_y.append((a, b, 1720))

    def apontadas(self, t_cima, t_baixo, t1, largura=300, alto=400):
        """"Resultados como esses aqui" com a pessoa apontando: os prints entram em cima quando ela aponta pra cima
        e embaixo quando aponta pra baixo, sem cobrir o rosto. A legenda desce para o pé da tela."""
        def legivel(nome):
            try:
                with open(os.path.join(self.provas, nome), "rb") as f:
                    f.read(4)
                return True
            except PermissionError:
                return False

        nomes = [n for n in provas_da_pasta(self.provas) if legivel(n)]
        xs = [(m.W - 3 * largura) // 4 * (i + 1) + largura * i for i in range(3)]
        for fila, (t0, y) in enumerate(((t_cima, 70), (t_baixo, m.H - alto - 120))):
            for i in range(3):
                nome = nomes[(fila * 3 + i) % len(nomes)]
                img = m.ImageOps.exif_transpose(m.Image.open(os.path.join(self.provas, nome))).convert("RGB")
                h = min(img.height, round(img.width * alto / largura))  # recorta o topo do print em 3:4
                card = m.card_imagem(img.crop((0, 0, img.width, h)), largura, raio=22)
                ti = t0 + 0.12 * i
                self.grafico(card, ti, t1, y + (12 if i == 1 else 0), x=xs[i])
                self.som(ti, "caixa", -4)
        self.ed.cap_y.append((t_cima, t1, 1180))

    def efeito(self, a, b, fx, sn=None, sem_legenda=False, **opcoes):
        """Efeito de vídeo num trecho de fala (opcional, via EDICAO_FX). A chave segue a posição no corpo."""
        if not FX or not os.path.isfile(os.path.join(FX, "scripts", "fx.py")):
            if opcoes.get("text"):
                self.pilula(opcoes["text"], a, b, sn=sn or "pop")
            return
        pasta = os.path.join(self.trab, "fx")
        os.makedirs(pasta, exist_ok=True)
        plano = {"effects": [{"fx": fx, "start": 0, "end": round(b - a, 3), **opcoes}]}
        pc = self.p.PRIMEIRA_DO_CORPO
        corpo = self.ed.tempo(pc, self.ed.tokens[pc][0]["s"])
        etiqueta = self.p.GANCHO if a < corpo else "corpo"
        chave = hashlib.md5(json.dumps([etiqueta, round((a - corpo) * m.FPS), round((b - corpo) * m.FPS), plano],
                                       sort_keys=True).encode()).hexdigest()[:12]
        saida = os.path.join(pasta, f"{fx}_{chave}.mp4")
        if not os.path.exists(saida):
            ent = saida + ".in.mp4"
            self.ed.trecho_fala(a, b, ent)
            arq_plano = saida + ".json"
            with open(arq_plano, "w") as f:
                json.dump(plano, f, ensure_ascii=False)
            subprocess.run([os.path.join(FX, ".venv/bin/python"), os.path.join(FX, "scripts/fx.py"), "--plan", arq_plano, ent, saida],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(ent)
        self.ed.adicionar_cena(a, b, saida, puro=True)
        if sn:
            self.som(a, sn)
        if sem_legenda:
            self.ed.sem_legenda.append((a, b))

    def _secoes(self):
        ordem = []
        for bl in self.p.BLOCOS:
            t = bl["takes"][0]
            ordem.append({**bl, "t0": self.ed.tempo(t, self.ed.tokens[t][0]["s"])})
        ordem[0]["t0"] = 0.0
        for a, b in zip(ordem, ordem[1:]):
            a["t1"] = b["t0"]
        ordem[-1]["t1"] = self.ed.duracao
        return ordem

    def _sons_de_corte(self):
        ocupados = sorted(t for t, _, _ in self.ed.sons)
        for i, t in enumerate(sorted(self.sons_cena)):
            if not any(abs(t - o) < 0.45 for o in ocupados):
                if getattr(self.p, "SONS_VARIADOS", False):
                    self.som(t, ["swoosh", "whoosh_curto", "swoosh_grave"][i % 3], [-2, -5, -3][i % 3])
                else:
                    self.som(t, "whoosh_curto", [-3, -7, -5][i % 3])

    def rodar(self, montar):
        """montar() registra cenas, efeitos e grafismos. 'base' no argv renderiza só as cenas."""
        ed = self.ed
        ed.secoes = self._secoes()
        if os.path.isdir(self.ov):
            shutil.rmtree(self.ov)
        os.makedirs(self.ov)
        montar()
        if getattr(self.p, "SONS_VARIADOS", False):
            self.sons_por_palavra()
        self._sons_de_corte()
        base = ed.render_base()
        print(f"dur={ed.duracao:.1f} final={ed.duracao / getattr(self.p, 'VELOCIDADE', 1):.1f} planos={ed.n_planos} "
              f"apoio={ed.cobertura:.0%} menor_fala={ed.menor_fala:.2f}s curtas={ed.falas_curtas}", flush=True)
        if sys.argv[1:] == ["base"]:
            return
        ass = ed.legendas()
        audio = ed.audio()
        os.makedirs(os.path.dirname(self.p.SAIDA), exist_ok=True)
        tmp = os.path.join(self.trab, f"final{self.p.GANCHO}.mp4")
        ed.compor(base, ass, audio, tmp)
        shutil.move(tmp, self.p.SAIDA)
        print("FIM", self.p.SAIDA, flush=True)
