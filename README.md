# Máquinas de Ads com IA

Duas ferramentas para operar no **Claude Code** ou no **Codex**, conversando em português:

| Máquina | O que faz | Você pede assim |
|---|---|---|
| **Edição** (`edicao/`) | Transforma takes crus do celular num anúncio vertical pronto: cortes na onda do áudio, legenda dinâmica, cenas de apoio na palavra exata, peças animadas, efeitos sonoros, trilha por emoção e checagem de qualidade. | "Edita os brutos da pasta `brutos/ad01` como um profissional" |
| **Meta Ads** (`meta-ads/`) | Sobe os vídeos como anúncios no Meta: campanha CBO, conjuntos com 3 a 4 anúncios, copy, pixel e Instagram. Depois confere a revisão, apaga os reprovados e ativa os aprovados. | "Sobe na conta ca01 os ads 1 a 12 da pasta X com a copy Y, R$ 250 por dia" |

A IA lê as instruções em `skills/` e roda os scripts por você.

---

## 1. Instalar

**Edição:** macOS (usa o Vision da Apple para achar rostos e ler texto). Python 3.10 ou mais novo.
**Meta Ads:** qualquer sistema com Python 3.

```bash
git clone <url-deste-repositorio> ~/maquinas-de-ads-ia
```

```bash
brew install ffmpeg python && xcode-select --install
```

```bash
cd ~/maquinas-de-ads-ia && pip3 install -r edicao/sistema/requirements.txt -r meta-ads/requirements.txt
```

```bash
python3 ~/maquinas-de-ads-ia/edicao/sistema/verificar.py
```

O `ffmpeg` precisa dos filtros `ass`, `tpad` e `ebur128`: o `verificar.py` confere. Se faltar, use `brew install ffmpeg-full`.

### Ligar na sua IA

**Claude Code:** copie as skills para a sua pasta de skills.

```bash
mkdir -p ~/.claude/skills && cp -R ~/maquinas-de-ads-ia/skills/* ~/.claude/skills/
```

**Codex:** abra o Codex dentro da pasta do repositório. Ele lê o `AGENTS.md`, que aponta para as mesmas instruções.

Se clonar em outro lugar, defina `MAQUINAS_ADS` com o caminho (por exemplo, no seu `~/.zshrc`).

---

## 2. Máquina de edição

### O que você precisa colocar (fica só no seu computador)

| Pasta | O quê |
|---|---|
| `edicao/brutos/<id>/` | Os takes do celular (`IMG_0001.MOV`…), um trecho de fala por arquivo |
| `edicao/musicas/` | 8 trilhas com licença comercial, uma por emoção (veja o LEIA-ME da pasta) |
| `edicao/banco/` | Vídeos e fotos de apoio: telas do seu produto, rotina, produtos, conquistas reais |
| `edicao/banco/provas/` | Prints de depoimento, com autorização e sem dados pessoais |

### Como funciona

1. `preparar_brutos.py <id>` converte HDR para SDR, extrai o áudio e transcreve palavra a palavra (Whisper).
2. Você (ou a IA) escreve o **plano** (`planos/<id>.py`): texto corrigido de cada take, destaques, blocos de emoção e trilhas.
3. O **gerador** (`gerar_<id>.py`) diz o que aparece em cada fala, preso à palavra: cena, tarja, sticker, lista riscada, contador, notificação, polaroide, prints.
4. O **motor** corta pela onda do áudio, monta, legenda, mixa (voz + trilha + efeitos, final em -15 LUFS) e exporta em 1080×1920.
5. O **portão** (`conferir.py`) checa quadro preto, volume, respiros longos, texto fora da zona segura e dado pessoal legível (telefone, e-mail, @, CPF), e gera uma folha de quadros.

Comece copiando `planos/exemplo.py` e `gerar_exemplo.py`. Na conversa, peça: *"edita os brutos de `brutos/ad01` seguindo a skill editar-ad"*.

**Efeitos de vídeo extras (opcional):** defina `EDICAO_FX` apontando para uma pasta com `scripts/fx.py`. Sem isso, `efeito()` vira uma tarja de texto e o vídeo sai normal.

---

## 3. Máquina de Meta Ads

1. Crie um app no [Meta for Developers](https://developers.facebook.com/) e **publique** (em modo desenvolvimento ele não cria criativos).
2. Na sua BM, crie um **usuário do sistema** com acesso às contas de anúncio, página, pixel e Instagram, e gere um token com `ads_management`, `ads_read`, `business_management` e `pages_read_engagement`.
3. Configure:

```bash
cd ~/maquinas-de-ads-ia/meta-ads && cp config.exemplo.json config.json
```

4. Cole o token em `config.json` (`bms.bm1.token`) e descubra os IDs:

```bash
python3 sistema/subir.py --descobrir bm1
```

5. Preencha `contas` com o que apareceu e teste:

```bash
python3 sistema/subir.py --verificar --conta ca01
```

6. Escreva a copy em `copies/<nome>.txt` (formato de `copies/exemplo.txt`) e simule antes de subir:

```bash
python3 sistema/subir.py --conta ca01 --pasta "/caminho/dos/videos" --ads 1-12 --copy exemplo --orcamento 250 --simular
```

Os nomes dos vídeos precisam ter `AD` + número (ex.: `PRODUTO - AD012.mp4`).

Outras rotinas:

- `sistema/reavaliacao_tardia.py` acha anúncios que o Meta derrubou depois de aprovar.
- `sistema/ativar_aprovados.py` ativa aprovados que nunca gastaram. Dá para agendar no cron a cada 20 minutos.
- `sistema/listar_vencedores.py` soma gasto e compras por anúncio em todas as contas.

**O `config.json` nunca vai para o GitHub** (está no `.gitignore`). Não cole seu token em lugar nenhum além dele.

---

## Boas práticas

- Promessa de renda não vira título nem tarja na tela. Valores só aparecem em print real de prova.
- Use só música e imagens com direito de uso, e prints de depoimento com autorização.
- A IA não ouve o áudio. Confira cada vídeo na escuta antes de subir.

## Licença

Código em MIT (veja `LICENSE`). Fontes em SIL Open Font License (`edicao/sistema/fontes`). Stickers do Noto Emoji em Apache 2.0 (`edicao/sistema/stickers`). Os efeitos sonoros são sintetizados pelo próprio `sons.py`.
