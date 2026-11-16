import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from subir import carregar_config, conta_da_config, meta_da_bm, rotulo_base, MetaErro

from reavaliacao_tardia import CONTAS_ATIVAS as CONTAS

def main():
    cfg = carregar_config()
    agregado = {}  # rotulo_base -> {"spend": x, "purchases": y, "contas": set()}
    for apelido in CONTAS:
        c = conta_da_config(cfg, apelido)
        meta = meta_da_bm(cfg, c["bm"])
        try:
            status = meta.get(c["ad_account_id"], fields="account_status")
            if status.get("account_status") != 1:
                print(f"[{c['sigla']}] não ativa, pulando.")
                continue
            insights = meta.get(f"{c['ad_account_id']}/insights", level="ad",
                                 fields="ad_name,spend,actions", date_preset="maximum", limit=500).get("data", [])
        except MetaErro as e:
            print(f"[{c['sigla']}] erro: {e}")
            continue
        for i in insights:
            nome = i.get("ad_name", "")
            spend = float(i.get("spend", 0) or 0)
            compras = 0
            for a in (i.get("actions") or []):
                if a.get("action_type") == "purchase":
                    compras = int(float(a.get("value", 0)))
                    break
            if compras == 0 and spend == 0:
                continue
            base = rotulo_base(nome) or nome
            e_ = agregado.setdefault(base, {"spend": 0.0, "compras": 0, "contas": set(), "nomes": set()})
            e_["spend"] += spend
            e_["compras"] += compras
            e_["contas"].add(c["sigla"])
            e_["nomes"].add(nome)
        print(f"[{c['sigla']}] ok")

    print("\n=== VENCEDORES (gasto > 0 e/ou compras > 0, agregado por ad raiz) ===")
    linhas = sorted(agregado.items(), key=lambda kv: -kv[1]["compras"])
    for base, d in linhas:
        if d["compras"] == 0:
            continue
        cpa = d["spend"] / d["compras"] if d["compras"] else 0
        print(f"{base}: R${d['spend']:.2f} gasto, {d['compras']} compras, CPA R${cpa:.2f}, contas: {sorted(d['contas'])}")

if __name__ == "__main__":
    main()
