# Instruções para agentes (Codex e outros)

Este repositório tem duas máquinas operadas por conversa. Antes de agir, leia a skill da tarefa e siga o fluxo dela:

- Editar um anúncio em vídeo a partir de brutos: `skills/editar-ad/SKILL.md` (código em `edicao/sistema`).
- Subir anúncios no Meta Ads: `skills/subir-ads/SKILL.md` (código em `meta-ads/sistema`).

Regras gerais:

- Responda em português do Brasil.
- Nunca escreva, invente ou exiba tokens. O token fica só em `meta-ads/config.json`, preenchido pela própria pessoa.
- Nada é subido no Meta sem pedido explícito. Rode sempre com `--simular` antes e mostre o plano.
- Você não ouve áudio: meça os níveis e liste o que a pessoa precisa conferir na escuta.
- Renders e uploads são lentos: rode em segundo plano quando puder.
- Não grave vídeos, prints ou dados pessoais em pastas versionadas (veja `.gitignore`).
