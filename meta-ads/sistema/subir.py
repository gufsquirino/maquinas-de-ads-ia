#!/usr/bin/env python3
"""MAQUINA ADS — sobe vídeos como anúncios no Meta Ads (campanha CBO, tudo PAUSADO).

Exemplos:
  python3 subir.py --conta ca01 --pasta "/caminho/dos/videos" --ads 80-90 --copy exemplo \
      --por-conjunto 3-4 --orcamento 250 --simular
  python3 subir.py --verificar --conta ca01
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent
CONFIG = RAIZ / "config.json"
COPIES = RAIZ / "copies"
STAGING = BASE / "staging"
HISTORICO = RAIZ / "historico"
CACHE = BASE / "cache_videos.json"
VIDEO_EXT = {".mp4", ".mov", ".m4v"}


# ---------------------------------------------------------------- config / API

def carregar_config():
    if not CONFIG.exists():
        sys.exit(f"Faltando {CONFIG}. Copie config.exemplo.json para config.json e preencha.")
    return json.loads(CONFIG.read_text())


def meta_da_bm(cfg, bm):
    bms = cfg.get("bms", {})
    if bm not in bms:
        sys.exit(f"BM '{bm}' não está em config.json. BMs: {', '.join(bms)}")
    return Meta(bms[bm].get("token", ""), cfg.get("api_version", "v26.0"))


class MetaErro(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


LIMITE_CHAMADAS = {4, 17, 32, 613, 80004}
TRANSITORIOS = {1, 2}  # "erro desconhecido" / "reduza a quantidade de dados": costuma passar ao repetir


class Meta:
    def __init__(self, token, versao):
        if not token or token.startswith("COLE"):
            sys.exit("Token dessa BM não configurado em config.json (bms → token).")
        self.token = token
        self.url = f"https://graph.facebook.com/{versao}"
        self.url_video = f"https://graph-video.facebook.com/{versao}"

    def _tratar(self, r):
        try:
            j = r.json()
        except ValueError:
            raise MetaErro(f"HTTP {r.status_code}: {r.text[:300]}")
        if "error" in j:
            e = j["error"]
            msg = e.get("error_user_msg") or e.get("message")
            titulo = e.get("error_user_title", "")
            raise MetaErro(f"{titulo} {msg} (code {e.get('code')}/{e.get('error_subcode')})".strip(), e.get("code"))
        return j

    def _chamar(self, fazer):
        """Executa a chamada; se o Meta acusar excesso de chamadas, espera e tenta de novo."""
        for tentativa in range(6):
            try:
                return self._tratar(fazer())
            except MetaErro as e:
                if e.code not in LIMITE_CHAMADAS | TRANSITORIOS or tentativa == 5:
                    raise
                espera = (60 if e.code in LIMITE_CHAMADAS else 15) * (tentativa + 1)
                print(f"   [Meta instável: {e}] tentando de novo em {espera}s...", flush=True)
                time.sleep(espera)

    def get(self, caminho, **params):
        params["access_token"] = self.token
        return self._chamar(lambda: requests.get(f"{self.url}/{caminho}", params=params, timeout=60))

    def post(self, caminho, dados):
        corpo = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in dados.items()}
        corpo["access_token"] = self.token
        return self._chamar(lambda: requests.post(f"{self.url}/{caminho}", data=corpo, timeout=120))

    def apagar(self, objeto):
        return self._chamar(lambda: requests.delete(f"{self.url}/{objeto}",
                                                    params={"access_token": self.token}, timeout=60))

    def subir_video(self, conta, arquivo, nome):
        tipo = "video/quicktime" if str(arquivo).lower().endswith(".mov") else "video/mp4"

        def enviar():
            with open(arquivo, "rb") as f:
                return requests.post(
                    f"{self.url_video}/{conta}/advideos",
                    data={"access_token": self.token, "name": nome},
                    files={"source": (Path(arquivo).name, f, tipo)},
                    timeout=900,
                )
        return self._chamar(enviar)["id"]

    def esperar_video(self, video_id, limite=900):
        inicio = time.time()
        while time.time() - inicio < limite:
            st = self.get(video_id, fields="status").get("status", {})
            estado = st.get("video_status")
            if estado == "ready":
                return
            if estado == "error":
                raise MetaErro(f"Meta recusou o vídeo {video_id}: {st}")
            time.sleep(5)
        raise MetaErro(f"Vídeo {video_id} não ficou pronto em {limite}s")

    def subir_imagem(self, conta, arquivo):
        """Sobe uma imagem estática pro álbum de imagens da conta; devolve a URL permanente dela
        (ao contrário do URI de /thumbnails de vídeo, que é temporário e pode sumir na hora da revisão)."""
        def enviar():
            with open(arquivo, "rb") as f:
                return requests.post(
                    f"{self.url}/{conta}/adimages",
                    data={"access_token": self.token},
                    files={"arquivo": (Path(arquivo).name, f, "image/jpeg")},
                    timeout=120,
                )
        resp = self._chamar(enviar)
        img = next(iter(resp["images"].values()))
        return img["url"]

    def thumbnail(self, video_id):
        for _ in range(12):
            dados = self.get(f"{video_id}/thumbnails", fields="uri,is_preferred").get("data", [])
            if dados:
                pref = [t for t in dados if t.get("is_preferred")]
                return (pref or dados)[0]["uri"]
            time.sleep(5)
        raise MetaErro(f"Sem thumbnail para o vídeo {video_id}")


# ---------------------------------------------------------------- arquivos

def finder(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def listar_pasta(pasta):
    try:
        return sorted(os.listdir(pasta))
    except PermissionError:
        # macOS bloqueia Downloads para o terminal; o Finder consegue ler.
        saida = finder(
            'set AppleScript\'s text item delimiters to linefeed\n'
            f'tell application "Finder" to get name of every file of folder (POSIX file "{pasta}" as alias)\n'
            'return result as text'
        )
        return sorted(n for n in saida.split("\n") if n)


def arquivo_legivel(caminho):
    try:
        with open(caminho, "rb") as f:
            f.read(1)
        return Path(caminho)
    except PermissionError:
        STAGING.mkdir(parents=True, exist_ok=True)
        finder(
            f'tell application "Finder" to duplicate (POSIX file "{caminho}" as alias) '
            f'to folder (POSIX file "{STAGING}" as alias) with replacing'
        )
        copia = STAGING / Path(caminho).name
        if not copia.exists():
            raise RuntimeError(f"Não consegui copiar {caminho} via Finder")
        return copia


def parse_faixa(texto):
    nums = set()
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" in parte:
            a, b = parte.split("-")
            nums.update(range(int(a), int(b) + 1))
        elif parte:
            nums.add(int(parte))
    return nums


def numero_do_ad(nome):
    """'PRODUTO - AD080-1.mp4' -> (80, 1); 'PRODUTO - AD082.mp4' -> (82, 0)."""
    stem = Path(nome).stem
    m = re.search(r"AD\s*0*(\d+)(?:-(\d+))?\s*$", stem, re.I)
    if m:
        return int(m.group(1)), int(m.group(2) or 0)
    nums = re.findall(r"\d+", stem)
    return (int(nums[-1]), 0) if nums else (None, 0)


def selecionar_videos(pasta, faixa, todos=False):
    if todos:
        # pasta inteira, um anúncio por arquivo (sem juntar versões pelo número)
        nomes = [n for n in listar_pasta(pasta)
                 if Path(n).suffix.lower() in VIDEO_EXT and not n.startswith(".")]
        return [(i, os.path.join(pasta, n)) for i, n in enumerate(nomes, 1)], []
    escolhidos = {}
    for nome in listar_pasta(pasta):
        if Path(nome).suffix.lower() not in VIDEO_EXT or nome.startswith("."):
            continue
        num, versao = numero_do_ad(nome)
        if num is None or (faixa and num not in faixa):
            continue
        # se existir AD080 e AD080-1, fica a versão mais nova
        if num not in escolhidos or versao > escolhidos[num][0]:
            escolhidos[num] = (versao, nome)
    faltando = sorted(faixa - set(escolhidos)) if faixa else []
    return [(n, os.path.join(pasta, escolhidos[n][1])) for n in sorted(escolhidos)], faltando


def rotulo_video(caminho):
    """'PRODUTO - AD080-1.mp4' -> 'AD080-1'; 'PRODUTO-SA - AD04.mp4' -> 'AD04'."""
    return Path(caminho).stem.split(" - ")[-1].strip()


def rotulo_base(rotulo):
    """'AD080-1' -> 'AD080' (tira a versão, pra comparar o mesmo ad independente do -N)."""
    return re.sub(r"-\d+$", "", rotulo.strip())


def ads_sujos(cfg):
    """Lê rejeitados.csv inteiro e devolve o conjunto de rótulos-base (sem -N) que já
    reprovaram em QUALQUER conta — candidatos a precisar de uma limpeza nova antes de
    irem pra outra conta."""
    import csv
    sujos = {}
    if not PLANILHA.exists():
        return sujos
    with open(PLANILHA, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            nome = row.get("anuncio", "")
            base = rotulo_base(rotulo_video(nome))
            sujos.setdefault(base, set()).add(row.get("conta", "?"))
    return sujos


def checar_ads_sujos(cfg, pasta):
    """Lista, pra cada vídeo da pasta, se o rótulo dele já reprovou em alguma conta."""
    sujos = ads_sujos(cfg)
    nomes = [n for n in listar_pasta(pasta) if Path(n).suffix.lower() in VIDEO_EXT and not n.startswith(".")]
    algum = False
    for n in sorted(nomes):
        base = rotulo_base(rotulo_video(n))
        if base in sujos:
            algum = True
            contas = ", ".join(sorted(sujos[base]))
            print(f"🔴 {n}  — {base} já reprovou em: {contas}  (limpar de novo antes de subir em conta nova)")
    if not algum:
        print("🟢 nenhum ad dessa pasta tem histórico de reprovação em alguma conta.")
    return sujos


def ler_copy(nome):
    caminho = Path(nome) if Path(nome).exists() else COPIES / f"{nome}.txt"
    if not caminho.exists():
        disponiveis = ", ".join(p.stem for p in COPIES.glob("*.txt"))
        sys.exit(f"Copy '{nome}' não encontrada. Disponíveis: {disponiveis}")
    campos, texto, no_texto = {}, [], False
    for linha in caminho.read_text().splitlines():
        m = re.match(r"^(TITULO2?|DESCRICAO2?|LINK|CTA|TEXTO2|TEXTO)\s*:\s*(.*)$", linha.strip(), re.I)
        if m:
            chave = m.group(1).upper()
            no_texto = chave == "TEXTO"
            if no_texto:
                if m.group(2):
                    texto.append(m.group(2))
            else:
                campos[chave] = m.group(2).strip()
        elif no_texto:
            texto.append(linha)
    campos["TEXTO"] = "\n".join(texto).strip()
    for obrig in ("TEXTO", "LINK"):
        if not campos.get(obrig):
            sys.exit(f"Copy '{caminho.name}' sem {obrig}.")
    return campos


def dividir(itens, minimo, maximo):
    """Divide em conjuntos de até `maximo`, o mais equilibrado possível.

    Usar o menor número de conjuntos que respeita o máximo já deixa o menor
    conjunto o maior possível; `minimo` só não é atingido quando não há vídeos suficientes.
    """
    n = len(itens)
    k = max(1, math.ceil(n / maximo))
    base, sobra = divmod(n, k)
    grupos, i = [], 0
    for g in range(k):
        tam = base + (1 if g < sobra else 0)
        grupos.append(itens[i:i + tam])
        i += tam
    return grupos


def sha1(caminho):
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


# ---------------------------------------------------------------- aprimoramentos

APRIMORAMENTOS = BASE / "aprimoramentos.json"


def carregar_aprimoramentos():
    return json.loads(APRIMORAMENTOS.read_text())


def salvar_aprimoramentos(a):
    APRIMORAMENTOS.write_text(json.dumps(a, indent=2, ensure_ascii=False))


def campos_desligados(apr, chaves=None):
    """Campos do criativo que desligam tudo: Advantage+ creative, mídia relacionada, multi-anunciante etc."""
    chaves = apr["features_off"] if chaves is None else chaves
    campos = {"degrees_of_freedom_spec": {
        "creative_features_spec": {
            **{k: {"enroll_status": "OPT_OUT"} for k in chaves},
            **{k: {"enroll_status": "OPT_IN"} for k in apr.get("features_on", [])}}}}
    campos.update(apr.get("campos_extras", {}))
    return campos


def criar_criativo(meta, conta, nome, spec, url_tags="", object_story_id=None, asset_feed_spec=None):
    """Cria o criativo com todos os aprimoramentos em OPT_OUT.

    A lista de features muda entre versões da API; se o Meta recusar alguma,
    ela é removida da lista (e salva) para não travar as próximas execuções.
    `object_story_id` reaproveita um post já existente (dark post) em vez de criar um novo.
    `asset_feed_spec` monta um criativo flexível (vários vídeos/títulos/descrições, o Meta escolhe a combinação).
    """
    apr = carregar_aprimoramentos()
    base = {"name": nome, "object_story_id": object_story_id} if object_story_id else \
           {"name": nome, "object_story_spec": spec}
    if asset_feed_spec:
        base["asset_feed_spec"] = asset_feed_spec
    if url_tags:
        base["url_tags"] = url_tags
    for _ in range(len(apr["features_off"]) + 1):
        try:
            return meta.post(f"{conta}/adcreatives", {**base, **campos_desligados(apr)})["id"]
        except MetaErro as e:
            msg = str(e).lower()
            ruins = [k for k in apr["features_off"] if k in msg or k.replace("_", " ") in msg]
            if not ruins:
                raise
            print(f"   [aviso] Meta não aceita {ruins} nesta versão — removendo da lista.")
            apr["features_off"] = [k for k in apr["features_off"] if k not in ruins]
            apr.setdefault("recusadas", []).extend(ruins)
            salvar_aprimoramentos(apr)
    raise MetaErro("Não consegui criar o criativo com os aprimoramentos desligados.")


def ligados_no_criativo(meta, criativo):
    """Lista o que o Meta deixou ligado sem a gente pedir (para avisar na revisão)."""
    apr = carregar_aprimoramentos()
    permitidos = set(apr.get("features_on", [])) | set(apr.get("campos_extras", {}))
    d = meta.get(criativo, fields="degrees_of_freedom_spec,contextual_multi_ads")
    feats = (d.get("degrees_of_freedom_spec") or {}).get("creative_features_spec") or {}
    ligados = [k for k, v in feats.items() if (v or {}).get("enroll_status") == "OPT_IN"]
    if (d.get("contextual_multi_ads") or {}).get("enroll_status") == "OPT_IN":
        ligados.append("contextual_multi_ads")
    return [k for k in ligados if k not in permitidos]


# ---------------------------------------------------------------- comandos

def conta_da_config(cfg, nome):
    contas = cfg.get("contas", {})
    if nome not in contas:
        sys.exit(f"Conta '{nome}' não está em config.json. Contas: {', '.join(contas)}")
    c = dict(contas[nome])
    if not str(c["ad_account_id"]).startswith("act_"):
        c["ad_account_id"] = f"act_{c['ad_account_id']}"
    return c


def descobrir(cfg, bm):
    """Mostra tudo que o token da BM enxerga, para preencher config.json."""
    meta = meta_da_bm(cfg, bm)
    print(f"BM '{bm}' — contas de anúncio:")
    for c in meta.get("me/adaccounts", fields="name,account_id,currency,account_status", limit=200)["data"]:
        print(f"  act_{c['account_id']}  {c['name']}  ({c['currency']}, status {c['account_status']})")
        try:
            for px in meta.get(f"act_{c['account_id']}/adspixels", fields="name,id", limit=50)["data"]:
                print(f"      pixel {px['id']}  {px['name']}")
        except MetaErro as e:
            print(f"      (pixels: {e})")
    print("\nPáginas:")
    for p in meta.get("me/accounts", fields="name,id,instagram_business_account{id,username}", limit=200)["data"]:
        ig = p.get("instagram_business_account") or {}
        extra = f"  IG @{ig.get('username')} id {ig.get('id')}" if ig else ""
        print(f"  {p['id']}  {p['name']}{extra}")


def verificar(cfg, nome):
    c = conta_da_config(cfg, nome)
    meta = meta_da_bm(cfg, c["bm"])
    a = meta.get(c["ad_account_id"], fields="name,currency,account_status,timezone_name")
    print(f"Conta  {c['ad_account_id']}: {a['name']} ({a['currency']}, status {a['account_status']}, {a['timezone_name']})")
    p = meta.get(c["page_id"], fields="name")
    print(f"Página {c['page_id']}: {p['name']}")
    px = meta.get(c["pixel_id"], fields="name")
    print(f"Pixel  {c['pixel_id']}: {px['name']}")
    if c.get("instagram_user_id"):
        print(f"Instagram id {c['instagram_user_id']}")
    print("OK.")


def inspecionar_ad(cfg, bm, ad_id, aprender):
    """Lê um anúncio feito à mão (com tudo desligado) e mostra/aprende os campos do criativo."""
    meta = meta_da_bm(cfg, bm)
    ad = meta.get(ad_id, fields="name,creative{id}")
    cid = ad["creative"]["id"]
    campos = ("name,object_story_spec,degrees_of_freedom_spec,contextual_multi_ads,"
              "asset_feed_spec,creative_sourcing_spec,url_tags,object_type")
    cr = meta.get(cid, fields=campos)
    HISTORICO.mkdir(exist_ok=True)
    arq = HISTORICO / f"inspecao_ad_{ad_id}.json"
    arq.write_text(json.dumps({"ad": ad, "criativo": cr}, indent=2, ensure_ascii=False))
    feats = (cr.get("degrees_of_freedom_spec") or {}).get("creative_features_spec") or {}
    print(f"Anúncio {ad['name']} — criativo {cid}  (completo em {arq})")
    for k, v in sorted(feats.items()):
        print(f"  {k}: {(v or {}).get('enroll_status')}")
    for extra in ("contextual_multi_ads", "creative_sourcing_spec", "asset_feed_spec"):
        if cr.get(extra):
            print(f"  {extra}: {json.dumps(cr[extra], ensure_ascii=False)}")
    if aprender:
        apr = carregar_aprimoramentos()
        novos = [k for k in feats if k not in apr["features_off"]]
        apr["features_off"] += novos
        if cr.get("contextual_multi_ads"):
            apr.setdefault("campos_extras", {})["contextual_multi_ads"] = {"enroll_status": "OPT_OUT"}
        salvar_aprimoramentos(apr)
        print(f"\nAprendido: {len(novos)} feature(s) novas adicionadas à lista de desligadas: {novos}")


PLANILHA = RAIZ / "rejeitados.csv"
PLANILHA_APROVADOS = RAIZ / "aprovados.csv"

APROVADO_STATUS = ("ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED")


def coletar_aprovados(cfg, contas=None):
    """Varre as contas e anota (sem duplicar) os anúncios aprovados com seu dark post ID."""
    import csv
    contas = contas or list(cfg["contas"])
    ja_tem = set()
    if PLANILHA_APROVADOS.exists():
        with open(PLANILHA_APROVADOS, encoding="utf-8-sig") as f:
            ja_tem = {row["ad_id"] for row in csv.DictReader(f, delimiter=";")}
    novo = not PLANILHA_APROVADOS.exists()
    linhas = []
    for sigla in contas:
        c = conta_da_config(cfg, sigla)
        meta = meta_da_bm(cfg, c["bm"])
        ads = meta.get(f"{c['ad_account_id']}/ads", limit=500,
                        fields="name,effective_status,adset{name},campaign{name},"
                               "creative{effective_object_story_id,video_id}")["data"]
        achados = [a for a in ads if a["effective_status"] in APROVADO_STATUS and a["id"] not in ja_tem
                   and (a.get("creative") or {}).get("effective_object_story_id")]
        for a in achados:
            post_id = a["creative"]["effective_object_story_id"].split("_")[-1]
            linhas.append([datetime.now().strftime("%Y-%m-%d %H:%M"), sigla, c["ad_account_id"],
                            (a.get("campaign") or {}).get("name", ""), (a.get("adset") or {}).get("name", ""),
                            a["name"], a["id"], a["effective_status"],
                            a["creative"]["effective_object_story_id"], post_id,
                            a["creative"].get("video_id", "")])
        print(f"[aprovados] {sigla}: {len(achados)} novo(s) de {len(ads)} anúncios totais")
    if linhas:
        with open(PLANILHA_APROVADOS, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            if novo:
                w.writerow(["data", "conta", "ad_account_id", "campanha", "conjunto", "anuncio", "ad_id",
                            "status", "object_story_id", "post_id", "video_id"])
            w.writerows(linhas)
        print(f"[aprovados] {len(linhas)} linha(s) nova(s) em {PLANILHA_APROVADOS}")
    else:
        print("[aprovados] nada novo para anotar")


def motivo_rejeicao(ad):
    fb = ad.get("ad_review_feedback") or {}
    partes = []
    for bloco in ("global", "placement_specific"):
        for k, v in (fb.get(bloco) or {}).items():
            partes.append(f"{k}: {v}" if isinstance(v, str) else k)
    for issue in ad.get("issues_info") or []:
        partes.append(issue.get("error_summary") or issue.get("error_message") or "")
    return " | ".join(p for p in partes if p) or "(Meta não informou o motivo pela API)"


def checar_rejeitados(cfg, apelido, campanha, esperar_min=0, excluir=True, ativar=True):
    """Espera, anota+exclui os reprovados e ativa os aprovados que estão pausados.

    "Aprovado" = effective_status PAUSED: passou pela revisão do Meta e só está desligado.
    Em análise (PENDING_REVIEW/IN_PROCESS) não é tocado.
    """
    c = conta_da_config(cfg, apelido)
    meta = meta_da_bm(cfg, c["bm"])
    if esperar_min:
        print(f"\n[rejeições] aguardando {esperar_min} min para o Meta revisar...", flush=True)
        time.sleep(esperar_min * 60)
    camp = meta.get(campanha, fields="name")["name"]
    ads = meta.get(f"{campanha}/ads", limit=200,
                   fields="name,effective_status,adset{name},ad_review_feedback,issues_info")["data"]
    reprovados = [a for a in ads if a["effective_status"] in ("DISAPPROVED", "WITH_ISSUES")]
    em_analise = [a["name"] for a in ads if a["effective_status"] in ("PENDING_REVIEW", "IN_PROCESS")]
    print(f"[rejeições] {camp}: {len(ads)} anúncios, {len(reprovados)} reprovados"
          + (f", {len(em_analise)} ainda em análise" if em_analise else ""))
    if reprovados:
        anotar_e_excluir(meta, c, camp, reprovados, excluir)
    if em_analise:
        print(f"[rejeições] ainda em análise (não mexi): {', '.join(em_analise)}")
    if ativar:
        candidatos = [a for a in ads if a["effective_status"] == "PAUSED"]
        # Nunca ativar um anúncio que já gastou — "PAUSED" pode ser aprovação nova
        # (nunca rodou) ou pausa manual de alguém depois de gastar. Só o 1º caso é seguro.
        gastos = {}
        if candidatos:
            insights = meta.get(f"{campanha}/insights", level="ad", fields="ad_id,spend",
                                 date_preset="maximum", limit=500).get("data", [])
            gastos = {i["ad_id"]: float(i.get("spend", 0)) for i in insights}
        aprovados = [a for a in candidatos if gastos.get(a["id"], 0) == 0]
        pulados = [a for a in candidatos if gastos.get(a["id"], 0) > 0]
        for a in aprovados:
            meta.post(a["id"], {"status": "ACTIVE"})
        print(f"[ativação] {len(aprovados)} anúncio(s) aprovado(s) ativado(s)"
              + (f": {', '.join(a['name'] for a in aprovados)}" if aprovados else ""))
        if pulados:
            print(f"[ativação] {len(pulados)} pausado(s) com gasto prévio, NÃO mexi (provável pausa manual): "
                  + ", ".join(f"{a['name']} (R${gastos.get(a['id'],0):.2f})" for a in pulados))
    return reprovados


def desempenho_ate_aqui(meta, ad_id):
    """Gasto/compras/CPA acumulados do anúncio até o momento (antes de excluir)."""
    try:
        ins = meta.get(ad_id, fields="insights.date_preset(maximum){spend,actions}") \
                   .get("insights", {}).get("data", [])
    except MetaErro:
        return "", "", ""
    if not ins:
        return "", "", ""
    i = ins[0]
    gasto = i.get("spend", "0")
    compras = sum(int(x["value"]) for x in (i.get("actions") or []) if x["action_type"] == "purchase")
    cpa = round(float(gasto) / compras, 2) if compras and float(gasto) else ""
    return gasto, compras, cpa


def anotar_e_excluir(meta, c, camp, reprovados, excluir):
    import csv
    novo = not PLANILHA.exists()
    with open(PLANILHA, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["data", "conta", "campanha", "conjunto", "anuncio", "ad_id", "status", "motivo",
                        "gasto", "compras", "cpa", "excluido"])
        for a in reprovados:
            gasto, compras, cpa = desempenho_ate_aqui(meta, a["id"])
            ok = "não"
            if excluir:
                try:
                    meta.apagar(a["id"])
                    ok = "sim"
                except MetaErro as e:
                    ok = f"erro: {e}"
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), c["sigla"], camp,
                        (a.get("adset") or {}).get("name", ""), a["name"], a["id"],
                        a["effective_status"], motivo_rejeicao(a), gasto, compras, cpa, ok])
            tag = " 🏆 VENCEDOR" if isinstance(compras, int) and compras > 0 else ""
            print(f"   ✗ {a['name']}: {motivo_rejeicao(a)}{tag} (gasto={gasto} compras={compras} cpa={cpa}) — excluído: {ok}")
    print(f"[rejeições] anotado em {PLANILHA}")


def nome_campanha(cfg, c, args):
    if args.nome:
        return args.nome
    modelo = cfg.get("padroes", {}).get("nome_campanha", "[{sigla}] [{produto}] [CBO] Teste ADs - {data}")
    return modelo.format(sigla=c["sigla"], produto=(args.produto or c["produto"]).upper(),
                         data=datetime.now().strftime("%Y.%m.%d"))


def ajustar_minimo(cfg, apelido, campanha_id, minimo_usd=None, aplicar=True):
    """Define (ou recalcula) o gasto mínimo diário por conjunto numa campanha CBO já ativa.

    Olha só os conjuntos ATIVOS (pausados não competem pelo orçamento). O mínimo nunca passa
    de orçamento_total / nº de conjuntos ativos — senão o Meta recusa a mudança.
    """
    c = conta_da_config(cfg, apelido)
    pad = cfg.get("padroes", {})
    meta = meta_da_bm(cfg, c["bm"])
    moeda = meta.get(c["ad_account_id"], fields="currency")["currency"]
    camp = meta.get(campanha_id, fields="name,daily_budget")
    orcamento_cents = int(camp["daily_budget"])
    minimo_usd = minimo_usd if minimo_usd is not None else pad.get("minimo_conjunto_usd", 10)
    if moeda == "USD":
        minimo_cents = round(minimo_usd * 100)
    else:
        minimo_cents = round(minimo_usd * pad.get("usd_brl_aprox", 5.3) * 100)

    adsets = meta.get(f"{campanha_id}/adsets", limit=200,
                       fields="name,status,effective_status,daily_min_spend_target")["data"]
    ativos = [a for a in adsets if a["status"] == "ACTIVE"]
    print(f"[mínimo] {camp['name']}: orçamento {orcamento_cents/100:.2f} {moeda}/dia, "
          f"{len(ativos)} conjunto(s) ativo(s) de {len(adsets)} total.")
    if not ativos:
        print("[mínimo] nenhum conjunto ativo, nada a fazer.")
        return

    teto = orcamento_cents // len(ativos)
    aplicado = min(minimo_cents, teto)
    if minimo_cents > teto:
        print(f"[mínimo] US$ {minimo_usd:.2f}/dia ({minimo_cents/100:.2f} {moeda}) × {len(ativos)} conjuntos passaria "
              f"do orçamento. Ajustando para {teto/100:.2f} {moeda}/dia por conjunto.")
    else:
        print(f"[mínimo] aplicando {aplicado/100:.2f} {moeda}/dia por conjunto (cabe nos {orcamento_cents/100:.2f} {moeda}/dia).")

    for a in ativos:
        atual = a.get("daily_min_spend_target")
        if atual == str(aplicado):
            print(f"   {a['name']}: já estava em {aplicado/100:.2f} {moeda}, pulando")
            continue
        if aplicar:
            meta.post(a["id"], {"daily_min_spend_target": str(aplicado)})
        print(f"   {a['name']}: {('(antes ' + str(int(atual)/100) + ') ' if atual else '')}-> {aplicado/100:.2f} {moeda}/dia"
              + ("" if aplicar else "  (simulação)"))


def subir_dark_post(cfg, args):
    """Campanha 1-1-1 (1 campanha, 1 conjunto, 1 anúncio) a partir de um post já aprovado,
    sem subir vídeo nenhum — reaproveita o object_story_id direto."""
    c = conta_da_config(cfg, args.conta)
    pad = cfg.get("padroes", {})
    copy = ler_copy(args.copy)
    meta = meta_da_bm(cfg, c["bm"])
    conta = c["ad_account_id"]
    moeda = meta.get(conta, fields="currency")["currency"]
    if args.orcamento is not None:
        if moeda != "BRL" and not args.moeda_ok:
            sys.exit(f"PAREI: a conta é em {moeda}, não em reais. Confirme o valor em {moeda} e rode com --moeda-ok.")
        orcamento = args.orcamento
    else:
        padrao_usd = pad.get("orcamento_1_1_1_usd", 50)
        orcamento = padrao_usd if moeda == "USD" else padrao_usd * pad.get("usd_brl_aprox", 5.3)
        print(f"[orçamento] usando o padrão de 1-1-1: US$ {padrao_usd:.2f}/dia (≈ {orcamento:.2f} {moeda})")
    args.orcamento = orcamento

    posts = [p.strip() for p in args.dark_post.split(",")]
    nomes_ads = [n.strip() for n in (args.dark_post_nome or "dark post").split(",")]
    if len(nomes_ads) == 1 and len(posts) > 1:
        nomes_ads = nomes_ads * len(posts)
    if len(nomes_ads) != len(posts):
        sys.exit(f"PAREI: {len(posts)} post(s) em --dark-post mas {len(nomes_ads)} nome(s) em --dark-post-nome — têm que bater.")
    object_story_ids = [p if "_" in p else f"{c['page_id']}_{p}" for p in posts]
    multi = len(posts) > 1
    nome_ad = nomes_ads[0]
    object_story_id = object_story_ids[0]
    rotulo_camp = f"[{nome_ad}]" if not multi else f"[{nomes_ads[0]}+{len(posts)-1}]"
    nome_camp = args.nome or f"[{c['sigla']}] [{(args.produto or c['produto']).upper()}] CBO 1-1-1 - {rotulo_camp} - {datetime.now():%Y.%m.%d}"
    evento = args.evento or c.get("evento") or pad.get("evento", "PURCHASE")
    cta = (copy.get("CTA") or pad.get("cta", "LEARN_MORE")).upper()
    idade = (pad.get("idade_min", 18), pad.get("idade_max", 50))
    status = {"campanha": "PAUSED", "conjunto": "PAUSED", "anuncio": "PAUSED", **pad.get("status", {})}

    print(f"Campanha {'1-1-N' if multi else '1-1-1'}: {nome_camp}")
    if multi:
        print(f"Conta: {args.conta} {conta}  |  {len(posts)} posts reaproveitados:")
        for n, oid in zip(nomes_ads, object_story_ids):
            print(f"   {n}: {oid}")
    else:
        print(f"Conta: {args.conta} {conta}  |  post reaproveitado: {object_story_id}")
    print(f"Orçamento: {args.orcamento:.2f} {moeda}/dia  |  Copy: {args.copy}  |  CTA {cta}")
    if args.simular:
        print("\n(simulação — nada foi enviado)")
        return

    camp = meta.post(f"{conta}/campaigns", {
        "name": nome_camp,
        "objective": args.objetivo or pad.get("objetivo", "OUTCOME_SALES"),
        "status": status["campanha"],
        "special_ad_categories": [],
        "daily_budget": str(round(args.orcamento * 100)),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    })["id"]
    print(f"[campanha] {camp}")

    otimizacao = args.otimizacao or c.get("otimizacao") or pad.get("otimizacao", "OFFSITE_CONVERSIONS")
    promoted_object = {"pixel_id": c["pixel_id"]} if otimizacao != "OFFSITE_CONVERSIONS" else \
                       {"pixel_id": c["pixel_id"], "custom_event_type": evento}
    dados_cj = {
        "name": "ADV",
        "campaign_id": camp,
        "status": status["conjunto"],
        "billing_event": "IMPRESSIONS",
        "optimization_goal": otimizacao,
        "promoted_object": promoted_object,
        "targeting": {
            "geo_locations": {"countries": args.paises.split(",") if args.paises else c.get("paises", pad.get("paises", ["BR"]))},
            "age_min": idade[0], "age_max": idade[1],
            "targeting_automation": {"advantage_audience": pad.get("advantage_audience", 0)},
        },
        **c.get("regulacao", {}),
    }
    locales_cj = [int(x) for x in args.locales.split(",")] if args.locales else c.get("locales")
    if locales_cj:
        dados_cj["targeting"]["locales"] = locales_cj
    cj = meta.post(f"{conta}/adsets", dados_cj)["id"]
    print(f"[conjunto] ADV: {cj}")

    for n, oid in zip(nomes_ads, object_story_ids):
        criativo = criar_criativo(meta, conta, n, None, pad.get("url_tags", ""), object_story_id=oid)
        ad = meta.post(f"{conta}/ads", {
            "name": n, "adset_id": cj, "creative": {"creative_id": criativo}, "status": status["anuncio"],
        })["id"]
        ligados = ligados_no_criativo(meta, criativo)
        print(f"[ad] {n}: {ad}" + (f"  ⚠ ainda ligado: {ligados}" if ligados else ""))

    link = (f"https://adsmanager.facebook.com/adsmanager/manage/ads?act={conta.removeprefix('act_')}"
            f"&selected_campaign_ids={camp}")
    print(f"\nPronto: 1 campanha, 1 conjunto, {len(posts)} anúncio(s) — sem subir vídeo, post(s) reaproveitado(s).")
    print(f"Revise e publique: {link}")

    espera = args.checar_apos if args.checar_apos is not None else pad.get("checar_rejeicoes_min", 20)
    if espera and espera > 0:
        checar_rejeitados(cfg, args.conta, camp, espera, ativar=not args.nao_ativar)


def subir(cfg, args):
    c = conta_da_config(cfg, args.conta)
    pad = cfg.get("padroes", {})
    copy = ler_copy(args.copy)
    if args.flexivel and not copy.get("TITULO2"):
        sys.exit("--flexivel precisa de pelo menos TITULO e TITULO2 na copy (TEXTO2/DESCRICAO/DESCRICAO2 são opcionais).")
    faixa = parse_faixa(args.ads) if args.ads else set()
    if args.arquivo:
        videos, faltando = [(i, os.path.join(args.pasta, n.strip()))
                            for i, n in enumerate(args.arquivo.split(","), 1)], []
    else:
        videos, faltando = selecionar_videos(args.pasta, faixa, args.todos)
    if not videos:
        sys.exit("Nenhum vídeo encontrado com esses números nessa pasta.")
    caminhos_por_num = {n: p for n, p in videos}
    mn, mx = (int(x) for x in (args.por_conjunto.split("-") + [args.por_conjunto])[:2])
    grupos = [videos] if args.conjunto else dividir(videos, mn, mx)

    nome_camp = nome_campanha(cfg, c, args)
    if args.todos and len({rotulo_video(v) for _, v in videos}) < len(videos):
        print("Aviso: há arquivos com o mesmo final de nome; os anúncios terão nomes parecidos.")
    cta = (copy.get("CTA") or pad.get("cta", "LEARN_MORE")).upper()
    evento = args.evento or c.get("evento") or pad.get("evento", "PURCHASE")
    idade = (pad.get("idade_min", 18), pad.get("idade_max", 50))
    status = {"campanha": "PAUSED", "conjunto": "PAUSED", "anuncio": "PAUSED", **pad.get("status", {})}
    rotulo = {"ACTIVE": "ativo", "PAUSED": "pausado"}

    print(f"Campanha: {nome_camp}  (CBO {args.orcamento:.2f}/dia na moeda da conta, {args.objetivo or pad.get('objetivo', 'OUTCOME_SALES')})")
    print(f"Status: campanha {rotulo[status['campanha']]} | conjuntos {rotulo[status['conjunto']]} | anúncios {rotulo[status['anuncio']]}")
    print(f"Conta: {args.conta} {c['ad_account_id']} (BM {c['bm']})  |  pixel {c['pixel_id']} → {evento}")
    print(f"Público: {idade[0]}-{idade[1]} anos  |  Copy: {args.copy}  |  CTA {cta}  |  aprimoramentos: desligados (exceto comentários, tradução e multi-anunciante)")
    print(f"Link: {copy['LINK']}")
    for i, g in enumerate(grupos, 1):
        print(f"  Conjunto {i:02d}: " + ", ".join(Path(v).name for _, v in g))
    if faltando:
        print(f"ATENÇÃO: não achei os ADs {faltando} na pasta.")
    if args.simular:
        print("\n(simulação — nada foi enviado)")
        return

    meta = meta_da_bm(cfg, c["bm"])
    conta = c["ad_account_id"]
    moeda = meta.get(conta, fields="currency")["currency"]
    if moeda != "BRL" and not args.moeda_ok:
        sys.exit(f"PAREI: a conta é em {moeda}, não em reais. O orçamento seria {args.orcamento} {moeda}/dia. "
                 f"Confirme o valor em {moeda} e rode com --moeda-ok.")

    minimo_usd = args.minimo_conjunto_usd if args.minimo_conjunto_usd is not None else pad.get("minimo_conjunto_usd", 10)
    if minimo_usd and minimo_usd > 0:
        if moeda == "USD":
            minimo_valor = minimo_usd
        else:
            taxa = pad.get("usd_brl_aprox", 5.3)
            minimo_valor = minimo_usd * taxa
        minimo_cents = round(minimo_valor * 100)
        print(f"Mínimo por conjunto: {minimo_valor:.2f} {moeda}/dia (≈ US$ {minimo_usd:.2f})")
    else:
        minimo_cents = None

    # 1) vídeos primeiro: se algum falhar, nada é criado na conta
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    subidos = {}
    for num, caminho in videos:
        local = arquivo_legivel(caminho)
        chave = f"{conta}:{sha1(local)}"
        if chave in cache:
            print(f"[vídeo] {local.name}: já enviado antes ({cache[chave]})")
            vid = cache[chave]
        else:
            print(f"[vídeo] enviando {local.name} ({local.stat().st_size / 1e6:.1f} MB)...", flush=True)
            vid = meta.subir_video(conta, local, local.stem)
            cache[chave] = vid
            CACHE.write_text(json.dumps(cache, indent=1))
        if local.parent == STAGING:
            local.unlink()  # cópia temporária do Finder, não acumula no disco
        subidos[num] = (vid, local.stem)
    for num, (vid, nome) in subidos.items():
        print(f"[vídeo] aguardando processamento de {nome}...", flush=True)
        meta.esperar_video(vid)

    # 2) campanha CBO (ou continua uma que parou no meio)
    existentes = {}
    fixo_cj = None
    minimos_existentes = 0  # soma do daily_min_spend_target já comprometido em conjuntos ativos
    if args.conjunto:
        info = meta.get(args.conjunto, fields="name,campaign_id,ads{name}")
        fixo_cj = info["name"]
        camp = args.campanha = info["campaign_id"]
        existentes[fixo_cj] = (args.conjunto, {a["name"] for a in (info.get("ads") or {}).get("data", [])})
        nome_camp = meta.get(args.campanha, fields="name")["name"]
        print(f"[conjunto] adicionando em '{fixo_cj}' da campanha '{nome_camp}'")
    elif args.campanha:
        camp = args.campanha
        for cj in meta.get(f"{camp}/adsets", fields="name,id,ads{name},status,daily_min_spend_target", limit=100)["data"]:
            existentes[cj["name"]] = (cj["id"], {a["name"] for a in (cj.get("ads") or {}).get("data", [])})
            if cj.get("status") == "ACTIVE":
                minimos_existentes += int(cj.get("daily_min_spend_target") or 0)
        print(f"[campanha] continuando {camp} ({len(existentes)} conjunto(s) já existentes)")
    else:
        camp = None
    camp = camp or meta.post(f"{conta}/campaigns", {
        "name": nome_camp,
        "objective": args.objetivo or pad.get("objetivo", "OUTCOME_SALES"),
        "status": status["campanha"],
        "special_ad_categories": [],
        "daily_budget": str(round(args.orcamento * 100)),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    })["id"]
    print(f"[campanha] {camp}")
    resultado = {"campanha": camp, "nome": nome_camp, "conta": conta, "conjuntos": []}

    nomes_grupos = [fixo_cj or f"CJ{i:02d} | {rotulo_video(g[0][1])}-{rotulo_video(g[-1][1])}"
                    for i, g in enumerate(grupos, 1)]
    if minimo_cents:
        novos = [n for n in nomes_grupos if n not in existentes]
        total_novos = max(len(novos), 1)
        orcamento_cents = int(meta.get(camp, fields="daily_budget")["daily_budget"])
        sobra = orcamento_cents - minimos_existentes
        teto = sobra // total_novos
        if minimo_cents > teto:
            print(f"[mínimo] {minimo_cents/100:.2f} {moeda}/dia × {total_novos} conjunto(s) novo(s) não cabe no que sobra do "
                  f"orçamento ({orcamento_cents/100:.2f} {moeda}/dia, já {minimos_existentes/100:.2f} comprometido nos existentes). "
                  f"Ajustando mínimo para {max(teto, 0)/100:.2f} {moeda}/dia por conjunto.")
            minimo_cents = teto if teto > 0 else None

    targeting = {
        "geo_locations": {"countries": args.paises.split(",") if args.paises else c.get("paises", pad.get("paises", ["BR"]))},
        "age_min": idade[0],
        "age_max": idade[1],
        "targeting_automation": {"advantage_audience": pad.get("advantage_audience", 0)},
    }
    locales_padrao = [int(x) for x in args.locales.split(",")] if args.locales else c.get("locales")
    if locales_padrao:
        targeting["locales"] = locales_padrao

    otimizacao = args.otimizacao or c.get("otimizacao") or pad.get("otimizacao", "OFFSITE_CONVERSIONS")
    if otimizacao == "LANDING_PAGE_VIEWS":
        billing_event = "IMPRESSIONS"
        promoted_object = None
    else:
        billing_event = "IMPRESSIONS"
        promoted_object = {"pixel_id": c["pixel_id"], "custom_event_type": evento}

    avisos = {}
    try:
        for i, g in enumerate(grupos, 1):
            nums = [n for n, _ in g]
            nome_cj = nomes_grupos[i - 1]
            cj, ja_tem = existentes.get(nome_cj, (None, set()))
            dados_cj = {
                "name": nome_cj,
                "campaign_id": camp,
                "status": status["conjunto"],
                "billing_event": billing_event,
                "optimization_goal": otimizacao,
                "targeting": targeting,
                **c.get("regulacao", {}),
            }
            if args.flexivel:
                dados_cj["is_dynamic_creative"] = True
            if promoted_object:
                dados_cj["promoted_object"] = promoted_object
            elif otimizacao in ("LINK_CLICKS", "LANDING_PAGE_VIEWS"):
                dados_cj["destination_type"] = "WEBSITE"
            if minimo_cents:
                dados_cj["daily_min_spend_target"] = str(minimo_cents)
            cj = cj or meta.post(f"{conta}/adsets", dados_cj)["id"]
            print(f"[conjunto] {nome_cj}: {cj}")
            info_cj = {"id": cj, "nome": nome_cj, "ads": []}
            if args.flexivel:
                nome_ad = nome_cj
                if nome_ad in ja_tem:
                    print(f"   [ad] {nome_ad}: já existe, pulando")
                else:
                    vids = [subidos[num][0] for num in nums]
                    thumbs = {}
                    with tempfile.TemporaryDirectory() as tmp:
                        for num in nums:
                            vid = subidos[num][0]
                            frame = Path(tmp) / f"{vid}.jpg"
                            subprocess.run(["ffmpeg", "-y", "-i", str(arquivo_legivel(caminhos_por_num[num])),
                                            "-ss", "1", "-vframes", "1", str(frame)],
                                           check=True, capture_output=True)
                            thumbs[vid] = meta.subir_imagem(conta, frame)
                            print(f"   [thumb] {vid}: imagem fixa enviada")
                    bodies = [{"text": copy["TEXTO"]}]
                    if copy.get("TEXTO2"):
                        bodies.append({"text": copy["TEXTO2"]})
                    asset_feed_spec = {
                        "videos": [{"video_id": v, "thumbnail_url": thumbs[v]} for v in vids],
                        "bodies": bodies,
                        "titles": [{"text": copy["TITULO"]}, {"text": copy["TITULO2"]}],
                        "link_urls": [{"website_url": copy["LINK"]}],
                        "call_to_action_types": [cta],
                        "ad_formats": ["AUTOMATIC_FORMAT"],
                    }
                    descricoes = [{"text": d} for d in (copy.get("DESCRICAO"), copy.get("DESCRICAO2")) if d]
                    if descricoes:
                        asset_feed_spec["descriptions"] = descricoes
                    spec = {"page_id": c["page_id"]}
                    if c.get("instagram_user_id"):
                        spec["instagram_user_id"] = c["instagram_user_id"]
                    criativo = criar_criativo(meta, conta, nome_ad, spec, pad.get("url_tags", ""),
                                               asset_feed_spec=asset_feed_spec)
                    ad = meta.post(f"{conta}/ads", {
                        "name": nome_ad,
                        "adset_id": cj,
                        "creative": {"creative_id": criativo},
                        "status": status["anuncio"],
                    })["id"]
                    ligados = ligados_no_criativo(meta, criativo)
                    if ligados:
                        avisos[nome_ad] = ligados
                    print(f"   [ad] {nome_ad} (flexível, {len(vids)} vídeos): {ad}" +
                          (f"  ⚠ ainda ligado: {ligados}" if ligados else ""))
                    info_cj["ads"].append({"id": ad, "nome": nome_ad, "video_ids": vids, "criativo": criativo})
            else:
                for num in nums:
                    vid, nome_ad = subidos[num]
                    if nome_ad in ja_tem:
                        print(f"   [ad] {nome_ad}: já existe, pulando")
                        continue
                    video_data = {
                        "video_id": vid,
                        "image_url": meta.thumbnail(vid),
                        "message": copy["TEXTO"],
                        "call_to_action": {"type": cta, "value": {"link": copy["LINK"]}},
                    }
                    if copy.get("TITULO"):
                        video_data["title"] = copy["TITULO"]
                    if copy.get("DESCRICAO"):
                        video_data["link_description"] = copy["DESCRICAO"]
                    spec = {"page_id": c["page_id"], "video_data": video_data}
                    if c.get("instagram_user_id"):
                        spec["instagram_user_id"] = c["instagram_user_id"]
                    criativo = criar_criativo(meta, conta, nome_ad, spec, pad.get("url_tags", ""))
                    ad = meta.post(f"{conta}/ads", {
                        "name": nome_ad,
                        "adset_id": cj,
                        "creative": {"creative_id": criativo},
                        "status": status["anuncio"],
                    })["id"]
                    ligados = ligados_no_criativo(meta, criativo)
                    if ligados:
                        avisos[nome_ad] = ligados
                    print(f"   [ad] {nome_ad}: {ad}" + (f"  ⚠ ainda ligado: {ligados}" if ligados else ""))
                    info_cj["ads"].append({"id": ad, "nome": nome_ad, "video_id": vid, "criativo": criativo})
            resultado["conjuntos"].append(info_cj)
    finally:
        HISTORICO.mkdir(exist_ok=True)
        arq = HISTORICO / f"{datetime.now():%Y-%m-%d_%H%M%S}_{args.conta}.json"
        arq.write_text(json.dumps(resultado, indent=2, ensure_ascii=False))

    link = (f"https://adsmanager.facebook.com/adsmanager/manage/ads"
            f"?act={conta.removeprefix('act_')}&selected_campaign_ids={camp}")
    total = sum(len(g["ads"]) for g in resultado["conjuntos"])
    print(f"\nPronto: 1 campanha, {len(resultado['conjuntos'])} conjuntos, {total} anúncios.")
    print(f"Status: campanha {rotulo[status['campanha']]}, conjuntos {rotulo[status['conjunto']]}, "
          f"anúncios {rotulo[status['anuncio']]} — nada gasta até você ativar os anúncios.")
    if avisos:
        print(f"⚠ O Meta manteve aprimoramentos ligados em {len(avisos)} anúncio(s): {avisos}")
    else:
        print("Aprimoramentos: conferidos via API — só os permitidos estão ligados.")
    print(f"Revise e publique: {link}")

    espera = args.checar_apos if args.checar_apos is not None else pad.get("checar_rejeicoes_min", 20)
    if espera and espera > 0:
        checar_rejeitados(cfg, args.conta, camp, espera,
                          ativar=not args.nao_ativar and pad.get("ativar_aprovados", True))


def main():
    ap = argparse.ArgumentParser(description="Sobe anúncios de vídeo no Meta Ads (CBO, pausado).")
    ap.add_argument("--conta", help="apelido da conta em config.json (ex.: ca01)")
    ap.add_argument("--pasta", help="pasta com os vídeos")
    ap.add_argument("--ads", help="números dos ADs, ex.: 80-90 ou 80,82,85-88 (vazio = todos)")
    ap.add_argument("--todos", action="store_true", help="sobe todos os vídeos da pasta, um por arquivo (sem juntar versões)")
    ap.add_argument("--copy", help="nome do arquivo em copies/ (sem .txt)")
    ap.add_argument("--produto", help="tag do produto no nome (padrão: o da conta, ex.: PRODUTO)")
    ap.add_argument("--por-conjunto", default="3-4", help="ads por conjunto, ex.: 3-4")
    ap.add_argument("--flexivel", action="store_true",
                     help="criativo flexível: cada conjunto vira 1 anúncio só, com todos os vídeos do grupo "
                          "+ 2 títulos (TITULO/TITULO2) + 2 descrições (DESCRICAO/DESCRICAO2) da copy; o Meta "
                          "testa as combinações sozinho. Use --por-conjunto para o nº de vídeos por anúncio (ex.: 3-3).")
    ap.add_argument("--orcamento", type=float, help="orçamento diário da campanha em reais")
    ap.add_argument("--nome", help="nome da campanha (substitui o padrão)")
    ap.add_argument("--checar-apos", type=int, help="minutos até checar/excluir reprovados (0 = não checar; padrão 20)")
    ap.add_argument("--checar-rejeicoes", metavar="CAMPANHA_ID", help="só checa/exclui reprovados de uma campanha (use com --conta)")
    ap.add_argument("--ajustar-minimo", metavar="CAMPANHA_ID", help="define o gasto mínimo diário por conjunto numa campanha já ativa (use com --conta)")
    ap.add_argument("--coletar-aprovados", action="store_true", help="anota em aprovados.csv os anúncios aprovados (com dark post ID); use --conta para limitar a uma conta")
    ap.add_argument("--ads-sujos", metavar="PASTA", help="lista os ads da pasta que já reprovaram em alguma conta (precisam ser limpos de novo antes da próxima)")
    ap.add_argument("--dark-post", help="cria campanha 1-1-1 reaproveitando um post já aprovado (post_id, ou page_id_post_id); use com --conta, --copy, --orcamento")
    ap.add_argument("--dark-post-nome", help="nome do anúncio/campanha ao usar --dark-post (padrão: 'dark post')")
    ap.add_argument("--nao-aplicar", action="store_true", help="com --ajustar-minimo: só mostra o que faria, não aplica")
    ap.add_argument("--nao-ativar", action="store_true", help="na checagem, não ativa os aprovados")
    ap.add_argument("--moeda-ok", action="store_true", help="confirma orçamento em conta que não é BRL")
    ap.add_argument("--arquivo", help="arquivo(s) exatos da pasta, separados por vírgula")
    ap.add_argument("--conjunto", help="ID de conjunto existente onde colocar os anúncios")
    ap.add_argument("--campanha", help="ID de campanha já criada para continuar (após erro)")
    ap.add_argument("--evento", help="evento de conversão (padrão: da conta ou PURCHASE)")
    ap.add_argument("--otimizacao", help="optimization_goal do conjunto (padrão: OFFSITE_CONVERSIONS; use LINK_CLICKS para maximizar cliques)")
    ap.add_argument("--objetivo", help="objective da campanha (padrão: OUTCOME_SALES; use OUTCOME_TRAFFIC para tráfego)")
    ap.add_argument("--minimo-conjunto-usd", type=float, help="gasto mínimo diário por conjunto, em US$ (padrão: 10; 0 desliga)")
    ap.add_argument("--paises", help="ex.: BR ou BR,PT")
    ap.add_argument("--locales", help="IDs de idioma (locale) do targeting, separados por vírgula, ex.: 1002 para espanhol (todas)")
    ap.add_argument("--simular", action="store_true", help="só mostra o plano, não envia nada")
    ap.add_argument("--descobrir", metavar="BM", help="lista contas, pixels, páginas e IGs que o token da BM acessa")
    ap.add_argument("--verificar", action="store_true", help="testa token, página e pixel da --conta")
    ap.add_argument("--inspecionar-ad", metavar="AD_ID", help="lê os aprimoramentos de um anúncio (use com --bm)")
    ap.add_argument("--bm", help="BM para --inspecionar-ad")
    ap.add_argument("--aprender", action="store_true", help="com --inspecionar-ad: adiciona as features achadas à lista de desligadas")
    args = ap.parse_args()
    cfg = carregar_config()

    try:
        if args.descobrir:
            return descobrir(cfg, args.descobrir)
        if args.verificar:
            return verificar(cfg, args.conta)
        if args.checar_rejeicoes:
            return checar_rejeitados(cfg, args.conta, args.checar_rejeicoes, args.checar_apos or 0,
                                     ativar=not args.nao_ativar)
        if args.ajustar_minimo:
            return ajustar_minimo(cfg, args.conta, args.ajustar_minimo, args.minimo_conjunto_usd,
                                  aplicar=not args.nao_aplicar)
        if args.coletar_aprovados:
            return coletar_aprovados(cfg, [args.conta] if args.conta else None)
        if args.ads_sujos:
            return checar_ads_sujos(cfg, args.ads_sujos)
        if args.dark_post:
            faltam = [k for k in ("conta", "copy") if getattr(args, k) is None]
            if faltam:
                ap.error("faltando: " + ", ".join("--" + f for f in faltam))
            return subir_dark_post(cfg, args)
        if args.inspecionar_ad:
            return inspecionar_ad(cfg, args.bm, args.inspecionar_ad, args.aprender)
        faltam = [k for k in ("conta", "pasta", "copy", "orcamento") if getattr(args, k) is None]
        if faltam:
            ap.error("faltando: " + ", ".join("--" + f for f in faltam))
        subir(cfg, args)
    except MetaErro as e:
        sys.exit(f"\nERRO do Meta: {e}")


if __name__ == "__main__":
    main()
