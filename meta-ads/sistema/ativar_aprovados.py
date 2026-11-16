import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from subir import carregar_config, conta_da_config, meta_da_bm, MetaErro
from reavaliacao_tardia import CONTAS_ATIVAS

NAO_ATIVAVEL = ("DISAPPROVED", "PENDING_REVIEW", "WITH_ISSUES", "IN_PROCESS", "PREAPPROVED")


def main():
    cfg = carregar_config()
    total = 0
    for apelido in CONTAS_ATIVAS:
        c = conta_da_config(cfg, apelido)
        meta = meta_da_bm(cfg, c["bm"])
        try:
            status = meta.get(c["ad_account_id"], fields="account_status")
        except MetaErro as e:
            print(f"[{c['sigla']}] erro ao checar conta: {e}")
            continue
        if status.get("account_status") != 1:
            print(f"[{c['sigla']}] conta não ativa (status {status.get('account_status')}), pulando.")
            continue
        try:
            ads = meta.get(
                f"{c['ad_account_id']}/ads", limit=500,
                fields="id,name,configured_status,effective_status,campaign{name,effective_status},"
                       "insights.date_preset(maximum){spend}",
            ).get("data", [])
        except MetaErro as e:
            print(f"[{c['sigla']}] erro ao listar anúncios: {e}")
            continue
        candidatos = [
            a for a in ads
            if a.get("configured_status") == "PAUSED"
            and a.get("effective_status") not in NAO_ATIVAVEL
            and (a.get("campaign") or {}).get("effective_status") == "ACTIVE"
        ]
        if not candidatos:
            continue
        for a in candidatos:
            insights = (a.get("insights") or {}).get("data") or []
            gasto = float(insights[0]["spend"]) if insights and insights[0].get("spend") else 0.0
            camp_nome = (a.get("campaign") or {}).get("name", "?")
            if gasto > 0:
                print(f"[{c['sigla']}] IGNORADO (gasto vitalício R${gasto:.2f}, pausado de propósito): {a['name']} [{a['id']}] — {camp_nome}")
                continue
            try:
                meta.post(a["id"], {"status": "ACTIVE"})
                print(f"[{c['sigla']}] ativado: {a['name']} [{a['id']}] ({a['effective_status']}, gasto vitalício R$0) — {camp_nome}")
                total += 1
            except MetaErro as e:
                print(f"[{c['sigla']}] erro ao ativar {a['id']}: {e}")
    print(f"\nTotal ativado(s): {total}")


if __name__ == "__main__":
    main()
