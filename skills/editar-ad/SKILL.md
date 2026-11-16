---
name: editar-ad
description: Edita anúncios verticais (Reels, TikTok, Stories) a partir de takes crus do celular com a máquina de edição deste repositório: legendas dinâmicas, cenas de apoio na palavra exata, peças animadas, efeitos sonoros, trilha por emoção e portão de qualidade. Use quando pedirem para editar, montar ou finalizar um ad ou criativo em vídeo a partir de uma pasta de brutos.
---

# Editar ad vertical

A máquina fica em `$MAQUINAS_ADS/edicao/sistema` (padrão: `~/maquinas-de-ads-ia/edicao/sistema`). Rode `python3 verificar.py` na primeira vez.

O ad nunca é "só a pessoa falando". Três coisas variam o tempo todo: **cena**, **música** e **legenda**.

## Passos

1. Brutos em `edicao/brutos/<id>/`. Copie `planos/exemplo.py` para `planos/<id>.py` e `gerar_exemplo.py` para `gerar_<id>.py` (troque `import exemplo` e `ID`).
2. `python3 preparar_brutos.py <id>`: converte HDR para SDR, extrai áudio 16 kHz e transcreve com Whisper (palavra a palavra). Coloque o nome da pessoa e termos do nicho em `EDICAO_TERMOS`.
3. Leia as transcrições (`.trabalho/<id>/txt/`) e escreva no plano o texto corrigido de cada take, com `*destaques*`.
   - Procure tropeços: tentativa abortada no meio do take, palavra esticada (> 1 s), pausa longa. Use `janela` ou `cortes`, ou retranscreva só o recomeço.
   - Takes de conversa com quem grava ficam de fora.
   - Liste no chat as palavras incertas. Nunca troque o sentido do que foi falado.
4. Divida o roteiro em `BLOCOS` de emoção (gancho, tensão, virada, empolgação, vitória, história, convite, urgência), cada um com faixa, início e ganho.
5. Para cada fala, pergunte "o que dá para mostrar aqui?" e escreva em `montar()`: cena, pílula, sticker, peça, prova. Tudo preso à palavra (`ini(take, "palavra")`).
6. `python3 gerar_<id>.py base` (só cenas, rápido) e depois `tudo`.
7. Portão: `python3 conferir.py <mp4> --trab .trabalho/trabalho_<id> --velocidade <VELOCIDADE>`. Olhe a folha de quadros que ele gera.
8. Entregue com os números (duração, % de apoio, LUFS) e a lista do que conferir na escuta: a IA não ouve o áudio.

## Regras que funcionam

- **Cenas de apoio em 30 a 40% do tempo**, só em fala concreta, até 3 s cada. Nunca deixe a pessoa só ~1 s entre duas cenas.
- A cena mostra o que está sendo dito, na palavra exata: "bolsa, óculos, relógio" são três imagens. Cena aleatória de banco de imagens sem relação com a fala é pior que o rosto.
- Pessoa citada pelo nome aparece com o print dela, nunca com foto de banco no lugar.
- Quando a pessoa aponta pra cima e pra baixo em "resultados como esses aqui", use `a.apontadas(t_cima, t_baixo, t1)`: os prints entram onde ela aponta.
- **Nada na altura da boca.** O motor já desce a legenda para baixo do queixo e encolhe as peças.
- Objeção imitada de alguém ("ah, mas como eu vou…"): voz levemente distorcida + preto e branco (`DISTORCER`, `PRETO_E_BRANCO`). Leve e rara.
- **Promessa de renda nunca vira pílula ou título.** Pode ficar na voz, mas não em destaque na tela. Valor só aparece em print real de prova.
- Música: uma faixa por bloco de emoção, subida caindo na palavra da virada. Final em **-15 LUFS**, com ganho fixo e limitador (sem loudnorm dinâmico).
- Clipe HDR (HLG) sem conversão entra lavado: o motor converte e grava BT.709.
- Confira o fundo dos brutos: quadro, TV ou tela podem mostrar dados ou promessas.
- Entregue sempre em versão nova, sem sobrescrever brutos nem a versão anterior.

## Ferramentas no gerador

`cena`, `pilula`/`a.sim`/`a.nao`/`a.tempo`, `sticker`, `prova`, `a.parede`, `a.apontadas`, `a.grafico`, `efeito` (opcional, `EDICAO_FX`) e as peças de `pecas.py`: `lista` (risca ou check), `contador`, `notificacao`, `polaroide`, `etiqueta`, `balao` (pergunta de outra pessoa), `logo`.
