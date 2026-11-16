import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from subir import (carregar_config, conta_da_config, meta_da_bm, anotar_e_excluir,
                    motivo_rejeicao, PLANILHA, MetaErro)

def _contas_ativas():
    """Contas a varrer: padroes.contas_ativas no config.json, ou todas as contas cadastradas."""
    import json
    from pathlib import Path
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    return cfg.get("padroes", {}).get("contas_ativas") or list(cfg.get("contas", {}))


CONTAS_ATIVAS = _contas_ativas()

def ja_registrados():
    ids = set()
    if PLANILHA.exists():
        with open(PLANILHA, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter=";"):
                ids.add(row.get("ad_id", ""))
    return ids

def vencedores_rejeitados():
    """Lista os anúncios rejeitados que já tinham venda antes de cair — prioridade de retestes."""
    if not PLANILHA.exists():
        print("Nenhum histórico de rejeições ainda.")
        return
    linhas = []
    with open(PLANILHA, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                compras = int(row.get("compras") or 0)
            except ValueError:
                compras = 0
            if compras > 0:
                linhas.append(row)
    if not linhas:
        print("Nenhum vencedor rejeitado registrado ainda (só passou a ser rastreado a partir de agora).")
        return
    linhas.sort(key=lambda r: (-int(r["compras"]), float(r["cpa"] or 1e9)))
    print(f"{'conta':6} {'anúncio':16} {'compras':8} {'gasto':>10} {'cpa':>10}  campanha")
    for r in linhas:
        print(f"{r['conta']:6} {r['anuncio']:16} {r['compras']:>8} {r['gasto']:>10} {r['cpa']:>10}  {r['campanha']}")
    print(f"\n{len(linhas)} anúncio(s) vencedor(es) rejeitado(s) — candidatos prioritários a limpar e retestar.")


def main():
    import sys as _sys
    if "--vencedores" in _sys.argv:
        vencedores_rejeitados()
        return
    excluir = "--excluir" in _sys.argv
    cfg = carregar_config()
    registrados = ja_registrados()
    total_novos = 0
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
        ads = meta.get(f"{c['ad_account_id']}/ads", limit=500,
                        fields="id,name,effective_status,adset{name},campaign{name,effective_status},ad_review_feedback,issues_info",
                        effective_status="['DISAPPROVED','WITH_ISSUES']").get("data", [])
        ads_ativos = [a for a in ads if (a.get("campaign") or {}).get("effective_status") == "ACTIVE"]
        novos = [a for a in ads_ativos if a["id"] not in registrados]
        print(f"[{c['sigla']}] {len(ads_ativos)} reprovado(s)/com problema em campanha ativa ({len(ads)} no total incl. campanhas paradas), {len(novos)} ainda não registrado(s).")
        if not novos:
            continue
        por_campanha = {}
        for a in novos:
            camp_nome = (a.get("campaign") or {}).get("name", "(campanha desconhecida)")
            por_campanha.setdefault(camp_nome, []).append(a)
        for camp_nome, lote in por_campanha.items():
            print(f"  -- {camp_nome} --")
            if excluir:
                anotar_e_excluir(meta, c, camp_nome, lote, excluir=True)
            else:
                for a in lote:
                    print(f"   (dry-run) {a['name']} [{a['id']}] {a['effective_status']}: {motivo_rejeicao(a)}")
            total_novos += len(lote)
    print(f"\nTotal de reavaliações tardias encontradas{'(dry-run, nada apagado)' if not excluir else ' e processadas'}: {total_novos}")

if __name__ == "__main__":
    main()
