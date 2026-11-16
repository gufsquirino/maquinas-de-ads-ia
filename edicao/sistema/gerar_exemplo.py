"""Gera o vídeo do planos/exemplo.py. Uso: python3 gerar_exemplo.py [base|tudo]

Cada linha diz o que aparece numa fala, presa à palavra exata (ini/fim). Ferramentas:
  cena(t0, t1, clipe, ini_src, foco=(x, y), z=zoom, pb=False)  vídeo/foto do banco em tela cheia
  pilula / a.sim / a.nao / a.tempo                              tarjas de texto (verde, vermelha, relógio)
  sticker(nome, t)                                              emoji pequeno longe do rosto (pasta stickers/)
  prova(arquivo, t0, t1)                                        print de depoimento de banco/provas
  a.parede(t0, t1)                                              paredão de prints
  a.apontadas(t_cima, t_baixo, t1)                              prints em cima/embaixo quando a pessoa aponta
  peca(nome, P.lista/contador/notificacao/polaroide/etiqueta/balao/logo, t0, t1)  peças animadas
  efeito(t0, t1, nome, text=...)                                efeito de vídeo opcional (EDICAO_FX)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "planos"))

import ad as A  # noqa: E402
import exemplo as p  # noqa: E402
import pecas as P  # noqa: E402

a = A.Ad(p, f"trabalho_{p.ID}")
ini, fim, fim_take, cena, prova, efeito, pilula, som, sticker = a.ini, a.fim, a.fim_take, a.cena, a.prova, a.efeito, a.pilula, a.som, a.sticker
PASTA = os.path.join(a.trab, "pecas")


def peca(nome, fabrica, t0, t1, **kw):
    return P.colocar(a.ed, PASTA, nome, fabrica, t0, t1, **kw)


def montar():
    # Gancho
    sticker("pensando", ini("0001", "Você"))
    t0, t1 = ini("0002", "o") - 0.1, fim_take("0002") + 0.3
    palavras = [(w, ini("0002", w) - t0) for w in ("o", "caminho")]
    peca("etiqueta", lambda d: P.etiqueta(palavras, d, destaque=("caminho",)), t0, t1, sons=[(t0, "pop", 0)])

    # Lista riscada do que não precisa
    t0, t1 = ini("0003", "estoque") - 0.25, fim_take("0003") + 0.2
    itens = [("Estoque", ini("0003", "estoque") - t0), ("Mostrar o rosto", ini("0003", "mostrar") - t0)]
    peca("lista", lambda d: P.lista("Sem *precisar* de", itens, d), t0, t1,
         sons=[(t0, "pop", 0)] + [(t0 + ti + 0.25, "erro", -2) for _, ti in itens])

    # Objeção e resposta com tela real (troque pelo clipe do seu banco)
    sticker("pensando", ini("0004", "Ah"))
    if os.path.exists(os.path.join(p.BANCO, "tela_produto.mp4")):
        cena(ini("0005", "vídeos"), fim_take("0005"), "tela_produto.mp4", 1.0)
    a.sim("VÍDEOS QUE ESTÃO BOMBANDO", ini("0005", "vídeos"), fim_take("0005") + 0.3, tam=42)

    # Chamada
    pilula("TOQUE EM SAIBA MAIS", ini("0006", "toca"), a.ed.duracao, y=1290, simbolo="👇", sn="sucesso", tam=50)


if __name__ == "__main__":
    a.rodar(montar)
