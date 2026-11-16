---
name: subir-ads
description: Sobe anúncios de vídeo no Meta Ads com a máquina deste repositório (meta-ads/sistema/subir.py). Use quando pedirem algo como "suba na conta X os ads 1-10 da pasta Y com a copy Z, 3 a 4 por conjunto, orçamento R$ 250", "subir criativos no meta", "criar campanha com esses vídeos".
---

# Subir ads no Meta

Script: `python3 "$MAQUINAS_ADS/meta-ads/sistema/subir.py"` (padrão: `~/maquinas-de-ads-ia`). Cria 1 campanha CBO + conjuntos + anúncios.
Status padrão: campanha e conjuntos ativos, anúncios pausados. Depois da revisão do Meta, o script ativa só os aprovados.

## Traduzir o pedido em argumentos

| Pedido | Argumento |
|---|---|
| "na conta X" | `--conta ca01` (apelido em `meta-ads/config.json` → `contas`) |
| "pasta Y" | `--pasta "<caminho absoluto>"` |
| "ads 1-10", "80, 82 e 85" | `--ads 1-10` / `--ads 80,82,85` (número `ADxxx` no nome do arquivo; pega a versão `-N` mais nova) |
| arquivo fora do padrão | `--arquivo "nome.mp4"` |
| "copy Z" | `--copy Z` (`meta-ads/copies/Z.txt`, formato de `copies/exemplo.txt`). Se a copy vier no chat, salve antes |
| "3 a 4 por conjunto" | `--por-conjunto 3-4` (padrão) |
| "R$ 250 por dia" | `--orcamento 250` (na moeda da conta) |

Se faltar conta, pasta, copy ou orçamento e não der para deduzir, pergunte. Nunca invente nem digite tokens.

## Fluxo

1. Rode com `--simular` e mostre o plano (campanha, conjuntos, vídeos de cada um, ADs não encontrados).
2. Se bater com o pedido, rode sem `--simular` em segundo plano: no fim ele espera `checar_rejeicoes_min` minutos e confere a revisão.
3. Reprovados são anotados em `rejeitados.csv` e excluídos. Aprovados pausados **que nunca gastaram** são ativados. Em análise não é tocado.
4. Responda com o resumo: aprovados, reprovados e link do Gerenciador.

## Configurar (primeira vez)

- Crie um app no Meta for Developers (publicado, não em modo desenvolvimento) e um **usuário do sistema** na BM com acesso às contas, página, pixel e Instagram. Gere o token com `ads_management`, `ads_read`, `business_management`, `pages_read_engagement`.
- `cp config.exemplo.json config.json`, cole o token em `bms.<bm>.token`.
- `python3 subir.py --descobrir bm1` lista contas, páginas, pixels e Instagram para preencher `contas`.
- `python3 subir.py --verificar --conta ca01` testa tudo.

## Lições de quem já subiu centenas de ads

- **Pausado não é "pronto para ativar".** Só ative pausado com gasto zero. Quem já gastou foi pausado por alguém.
- **3 a 4 anúncios por conjunto.** Não force tudo num conjunto só.
- **Volume derruba conta.** Em conta com histórico, não empilhe lotes grandes em dias seguidos: a taxa de reprovação dispara e o Meta reavalia até anúncios que já vendiam. Dê intervalo entre lotes.
- **Reavaliação tardia existe.** O Meta aprova, deixa rodar e derruba horas ou dias depois. Rode `reavaliacao_tardia.py` (sem `--excluir` para ver, com `--excluir` para documentar e apagar) nos dias seguintes a um lote grande.
- **Ad que reprovou numa conta não vai igual para outra.** Gere arquivo novo (reencode) antes; `--ads-sujos <pasta>` lista quem já reprovou.
- **Conta sem Instagram na BM nova:** a página precisa estar compartilhada com aquela BM e com o usuário do sistema. Nunca suba sem `instagram_user_id`.
- Conta em outra moeda: o script para e pede `--moeda-ok` com o valor já na moeda da conta.
- Escalar um vencedor sem novo upload: `--dark-post <post_id>` cria campanha 1-1-1 com o post aprovado (`--coletar-aprovados` grava os post IDs).
- Aprimoramentos automáticos de criativo ficam em `sistema/aprimoramentos.json` (desligados por padrão). `--inspecionar-ad <id> --bm <bm> --aprender` copia de um anúncio configurado à mão.
- Se parar no meio: corrija e rode de novo com `--campanha <ID>`. Ele reaproveita o que já foi criado.
