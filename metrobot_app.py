# -*- coding: utf-8 -*-
"""
🚇 MetrôBot SP 2.0 — App de desktop (chat + mapa da rota)
=========================================================
O usuário CONVERSA com a IA (Llama via Groq) em linguagem natural e o app
DESENHA o mapa da rota do metrô (Linhas 1-Azul, 2-Verde e 3-Vermelha).

- LLM funcional (Groq) com fallback automático para modo OFFLINE.
- Busca BFS/DFS + lógica de 1ª ordem (auditável) decidem a rota.
- Mapa desenhado num Canvas nativo do Tkinter (sem dependências pesadas).

Rodar:   python metrobot_app.py
Gerar exe:  pyinstaller --noconfirm --onefile --windowed --name MetroBotSP metrobot_app.py
"""

import os
import re
import sys
import json
import unicodedata
import threading
from collections import deque

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog

# ============================================================ LLM
PROVEDOR = "groq"  # "groq" | "offline"
MODELOS_PREFERIDOS = [
    "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
    "openai/gpt-oss-20b", "gemma2-9b-it",
]


def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def obter_chave_groq():
    # .env ao lado do app / exe, depois variável de ambiente
    try:
        from dotenv import load_dotenv
        for p in (os.path.join(_base_dir(), ".env"), os.path.join(os.getcwd(), ".env")):
            if os.path.exists(p):
                load_dotenv(p)
                break
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


def _candidatos_groq(cliente):
    try:
        dados = cliente.models.list().data
        cand = [m.id for m in dados
                if all(t not in m.id.lower() for t in ("guard", "whisper", "vision", "tts"))]
        ordenados = [m for m in MODELOS_PREFERIDOS if m in cand]
        ordenados += [m for m in cand if m not in ordenados]
        return ordenados or MODELOS_PREFERIDOS
    except Exception:
        return MODELOS_PREFERIDOS


def chamar_llm(mensagens, modo_json=False):
    if PROVEDOR != "groq":
        raise RuntimeError("Modo offline")
    from groq import Groq
    cliente = Groq(api_key=obter_chave_groq())
    extras = {"response_format": {"type": "json_object"}} if modo_json else {}
    erro = ""
    for modelo in _candidatos_groq(cliente):
        try:
            r = cliente.chat.completions.create(
                model=modelo, messages=mensagens, temperature=0, max_tokens=400, **extras)
            return r.choices[0].message.content
        except Exception as e:
            erro = f"{modelo}: {e}"
    raise RuntimeError(f"Groq falhou -> {erro}")


def llm_disponivel():
    if PROVEDOR != "groq":
        return False, "offline"
    try:
        import groq  # noqa
    except Exception:
        return False, "biblioteca 'groq' não instalada"
    if not obter_chave_groq():
        return False, "GROQ_API_KEY não encontrada"
    return True, "Groq"


# ============================================================ DADOS
LINHAS = {
    "Linha 1-Azul": [
        "Tucuruvi", "Parada Inglesa", "Jardim São Paulo", "Santana",
        "Carandiru", "Portuguesa-Tietê", "Armênia", "Tiradentes", "Luz",
        "São Bento", "Sé", "Japão-Liberdade", "São Joaquim", "Vergueiro",
        "Paraíso", "Ana Rosa", "Vila Mariana", "Santa Cruz",
        "Praça da Árvore", "Saúde", "São Judas", "Conceição", "Jabaquara",
    ],
    "Linha 2-Verde": [
        "Vila Madalena", "Sumaré", "Clínicas", "Consolação", "Trianon-Masp",
        "Brigadeiro", "Paraíso", "Ana Rosa", "Chácara Klabin",
        "Santos-Imigrantes", "Alto do Ipiranga", "Sacomã", "Tamanduateí",
        "Vila Prudente",
    ],
    "Linha 3-Vermelha": [
        "Palmeiras-Barra Funda", "Marechal Deodoro", "Santa Cecília",
        "República", "Anhangabaú", "Sé", "Pedro II", "Brás",
        "Bresser-Mooca", "Belém", "Tatuapé", "Carrão", "Penha",
        "Vila Matilde", "Guilhermina-Esperança", "Patriarca-Vila Ré",
        "Artur Alvim", "Corinthians-Itaquera",
    ],
}
CORES = {"Linha 1-Azul": "#0a6ed1", "Linha 2-Verde": "#1e9e58", "Linha 3-Vermelha": "#e2312d"}
LOCAIS = {
    "Pinacoteca": "Luz", "Catedral da Sé": "Sé", "Centro Cultural São Paulo": "Vergueiro",
    "MASP": "Trianon-Masp", "Hospital das Clínicas": "Clínicas", "Museu do Ipiranga": "Alto do Ipiranga",
    "Theatro Municipal": "Anhangabaú", "Neo Química Arena": "Corinthians-Itaquera",
    "Memorial da América Latina": "Palmeiras-Barra Funda",
}
ESTACOES_TODAS = sorted({e for linha in LINHAS.values() for e in linha})
OPCOES = [(f"📍 {l}", ("local", l)) for l in LOCAIS] + [(f"🚇 {e}", ("estacao", e)) for e in ESTACOES_TODAS]
OPCAO_POR_ROTULO = {rotulo: valor for rotulo, valor in OPCOES}
ROTULO_POR_VALOR = {valor: rotulo for rotulo, valor in OPCOES}
OPCAO_ROTULOS = [r for r, _ in OPCOES]


def construir_grafo_multilinhas(linhas):
    grafo, trechos = {}, {}
    for nome, ests in linhas.items():
        for i in range(len(ests) - 1):
            a, b = ests[i], ests[i + 1]
            grafo.setdefault(a, [])
            grafo.setdefault(b, [])
            if b not in grafo[a]:
                grafo[a].append(b)
            if a not in grafo[b]:
                grafo[b].append(a)
            trechos.setdefault((a, b), set()).add(nome)
            trechos.setdefault((b, a), set()).add(nome)
    return grafo, trechos


GRAFO, LINHAS_TRECHO = construir_grafo_multilinhas(LINHAS)


# ============================================================ COORDENADAS DO MAPA
NOME_MAPA = {
    "Jardim São Paulo": "Jd. S. Paulo",
    "Portuguesa-Tietê": "Tietê",
    "Japão-Liberdade": "Liberdade",
    "Praça da Árvore": "Pç. Árvore",
    "Palmeiras-Barra Funda": "Barra Funda",
    "Marechal Deodoro": "Deodoro",
    "Santa Cecília": "Sta. Cecília",
    "Bresser-Mooca": "Bresser",
    "Guilhermina-Esperança": "Guilhermina",
    "Patriarca-Vila Ré": "Patriarca",
    "Corinthians-Itaquera": "Itaquera",
    "Vila Madalena": "Vl. Madalena",
    "Trianon-Masp": "Trianon",
    "Chácara Klabin": "Klabin",
    "Santos-Imigrantes": "Imigrantes",
    "Alto do Ipiranga": "Ipiranga",
    "Vila Prudente": "Vl. Prudente",
    "Vila Matilde": "Vl. Matilde",
}


def nome_mapa(est):
    return NOME_MAPA.get(est, est)


def _coords():
    c = {}
    for i, e in enumerate(LINHAS["Linha 1-Azul"]):
        c[e] = (0.0, -float(i) * 1.15)
    y_se = c["Sé"][1]
    idx_se = LINHAS["Linha 3-Vermelha"].index("Sé")
    for i, e in enumerate(LINHAS["Linha 3-Vermelha"]):
        c.setdefault(e, ((i - idx_se) * 2.15, y_se))
    ln2 = LINHAS["Linha 2-Verde"]
    ip = ln2.index("Paraíso")
    y_par, y_ana = c["Paraíso"][1], c["Ana Rosa"][1]
    for i, e in enumerate(ln2):
        if e in c:
            continue
        if i < ip:
            off = ip - i
            c[e] = (-off * 2.35, y_par + off * 1.25)
        else:
            off = i - (ip + 1)
            c[e] = ((off + 1) * 2.35, y_ana - (off + 1) * 1.15)
    return c


def _lados_rotulo():
    """Cada estação tem um lado fixo para o nome — evita sobreposição."""
    lado = {}
    for e in LINHAS["Linha 1-Azul"]:
        lado[e] = "w"
    l3 = LINHAS["Linha 3-Vermelha"]
    se = l3.index("Sé")
    for i, e in enumerate(l3):
        if e == "Sé":
            continue
        lado[e] = "n" if i < se else "s"
        if i % 2 == (0 if i < se else 1):
            lado[e] = "n" if lado[e] == "s" else "s"
    l2 = LINHAS["Linha 2-Verde"]
    ip = l2.index("Paraíso")
    for i, e in enumerate(l2):
        if e in ("Paraíso", "Ana Rosa"):
            continue
        lado[e] = "nw" if i < ip else "se"
    lado["Sé"] = "sw"
    lado["Paraíso"] = "e"
    lado["Ana Rosa"] = "e"
    return lado


COORDS = _coords()
LADO_ROTULO = _lados_rotulo()


# ============================================================ BUSCA
def reconstruir(pai, destino):
    cam, at = [], destino
    while at is not None:
        cam.append(at)
        at = pai[at]
    return list(reversed(cam))


def bfs(grafo, origem, destino, bloqueadas=()):
    if origem in bloqueadas or destino in bloqueadas:
        return None, []
    fila = deque([origem])
    pai = {origem: None}
    ordem = []
    while fila:
        at = fila.popleft()
        ordem.append(at)
        if at == destino:
            return reconstruir(pai, destino), ordem
        for viz in grafo[at]:
            if viz not in pai and viz not in bloqueadas:
                pai[viz] = at
                fila.append(viz)
    return None, ordem


def dfs(grafo, origem, destino, bloqueadas=()):
    if origem in bloqueadas or destino in bloqueadas:
        return None, []
    vis, ordem = set(), []

    def go(at, cam):
        vis.add(at)
        ordem.append(at)
        if at == destino:
            return cam
        for viz in grafo[at]:
            if viz not in vis and viz not in bloqueadas:
                r = go(viz, cam + [viz])
                if r:
                    return r
        return None

    return go(origem, [origem]), ordem


def segmentar(caminho, trechos):
    if not caminho or len(caminho) < 2:
        return []
    segs = []
    emb = caminho[0]
    poss = trechos[(caminho[0], caminho[1])]
    atual = sorted(poss)[0]
    for i in range(1, len(caminho) - 1):
        a, b = caminho[i], caminho[i + 1]
        prox = trechos[(a, b)]
        inter = poss & prox
        if not inter:
            segs.append((atual, emb, a))
            atual = sorted(prox)[0]
            emb = a
            poss = prox
        else:
            poss = inter
            atual = sorted(inter)[0]
    segs.append((atual, emb, caminho[-1]))
    return segs


def contar_baldeacoes(caminho, trechos):
    segs = segmentar(caminho, trechos)
    if not segs:
        return 0, []
    return len(segs) - 1, [(ini, ln) for (ln, ini, _f) in segs[1:]]


def roteiro_textual(segs):
    partes = []
    for i, (ln, ini, fim) in enumerate(segs):
        if i == 0:
            partes.append(f"Embarque na {ln}: {ini} → {fim}")
        else:
            partes.append(f"↳ Baldeação em {ini}, siga na {ln} → {fim}")
    return "\n".join(partes)


# ============================================================ LÓGICA
def fatos_base():
    f = set()
    for nome, ests in LINHAS.items():
        for e in ests:
            f.add(("estacao", e))
            f.add(("pertence", e, nome))
    for l, e in LOCAIS.items():
        f.add(("proximo_de", l, e))
    return f


def consultar(f, pred):
    return [x[1:] for x in f if x[0] == pred]


def r_origem(f):
    n = set()
    for (l,) in consultar(f, "usuario_esta_em"):
        for (ll, e) in consultar(f, "proximo_de"):
            if ll == l:
                n.add(("origem", e))
    for (e,) in consultar(f, "usuario_esta_na_estacao"):
        n.add(("origem", e))
    return n


def r_destino(f):
    n = set()
    for (l,) in consultar(f, "usuario_quer_ir"):
        for (ll, e) in consultar(f, "proximo_de"):
            if ll == l:
                n.add(("destino", e))
    for (e,) in consultar(f, "usuario_quer_ir_estacao"):
        n.add(("destino", e))
    return n


def r_bloqueio(f):
    return {("bloqueada", e) for (e,) in consultar(f, "fechada")}


def r_acess(f):
    if not consultar(f, "precisa_acessibilidade"):
        return set()
    return {("inacessivel", e) for (e,) in consultar(f, "elevador_em_manutencao")}


def r_alerta(f):
    n = set()
    inac = {e for (e,) in consultar(f, "inacessivel")}
    for papel in ("origem", "destino"):
        for (e,) in consultar(f, papel):
            if e in inac:
                n.add(("alerta", papel, f"{e} (sem acessibilidade)"))
    return n


def r_integracao(f):
    pert = {}
    for (e, l) in consultar(f, "pertence"):
        pert.setdefault(e, set()).add(l)
    return {("integracao", e) for e, ls in pert.items() if len(ls) > 1}


def r_pico(f):
    if not consultar(f, "horario_pico"):
        return set()
    return {("alerta", "lotação", f"{e} (integração em horário de pico)")
            for (e,) in consultar(f, "integracao")}


REGRAS = [("R1", "", r_origem), ("R2", "", r_destino), ("R3", "", r_bloqueio),
          ("R4", "", r_acess), ("R5", "", r_alerta), ("R6", "", r_integracao), ("R7", "", r_pico)]


def encadear(f, regras):
    f = set(f)
    just = {}
    while True:
        novos = set()
        for nome, _fm, reg in regras:
            for fato in reg(f) - f:
                novos.add(fato)
                just[fato] = nome
        if not novos:
            return f, just
        f |= novos


INTEGRACOES = sorted(e for (e,) in consultar(encadear(fatos_base(), REGRAS)[0], "integracao"))


def _lugar(valor):
    """Aceita ('estacao'|'local', nome) ou o nome cru da estação/local."""
    if isinstance(valor, (tuple, list)) and len(valor) == 2:
        return valor[0], valor[1]
    if isinstance(valor, str):
        for e in ESTACOES_TODAS:
            if e == valor:
                return "estacao", e
        for l in LOCAIS:
            if l == valor:
                return "local", l
        r = resolver_nome(valor)
        if r:
            return r
    raise ValueError(f"Lugar inválido: {valor!r}")


def planejar(pedido, fechadas=(), manutencao=(), pico=False, algoritmo="BFS"):
    f = fatos_base()
    to, no = _lugar(pedido["origem"])
    td, nd = _lugar(pedido["destino"])
    f.add(("usuario_esta_em", no) if to == "local" else ("usuario_esta_na_estacao", no))
    f.add(("usuario_quer_ir", nd) if td == "local" else ("usuario_quer_ir_estacao", nd))
    if pedido.get("acessibilidade"):
        f.add(("precisa_acessibilidade",))
    if pico:
        f.add(("horario_pico",))
    for e in fechadas:
        f.add(("fechada", e))
    for e in manutencao:
        f.add(("elevador_em_manutencao", e))
    f, just = encadear(f, REGRAS)
    origens, destinos = consultar(f, "origem"), consultar(f, "destino")
    if not origens or not destinos:
        return {
            "origem": no, "destino": nd, "algoritmo": algoritmo,
            "caminho": None, "visitados": [], "bloqueadas": [],
            "alertas": [], "paradas": None, "qtd_baldeacoes": 0,
            "baldeacoes": [], "segmentos": [], "roteiro_detalhado": "",
            "tempo_min": None, "regras_usadas": [],
        }
    origem, destino = origens[0][0], destinos[0][0]
    bloq = {e for (e,) in consultar(f, "bloqueada")}
    alertas = consultar(f, "alerta")
    buscar = bfs if algoritmo == "BFS" else dfs
    caminho, visitados = buscar(GRAFO, origem, destino, bloq)
    segs = segmentar(caminho, LINHAS_TRECHO)
    qb, locs = contar_baldeacoes(caminho, LINHAS_TRECHO)
    return {
        "origem": origem, "destino": destino, "algoritmo": algoritmo,
        "caminho": caminho, "visitados": visitados, "bloqueadas": sorted(bloq),
        "alertas": [f"{p}: {e}" for p, e in alertas],
        "paradas": len(caminho) - 1 if caminho else None,
        "qtd_baldeacoes": qb, "baldeacoes": locs, "segmentos": segs,
        "roteiro_detalhado": roteiro_textual(segs),
        "tempo_min": ((len(caminho) - 1) * 2 + qb * 5) if caminho else None,
        "regras_usadas": sorted(set(just.values())),
    }


# ============================================================ INTÉRPRETE / NARRADOR
def normalizar(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


ALIAS = {
    "se": "Sé", "catedral": "Catedral da Sé", "catedral da se": "Catedral da Sé",
    "masp": "MASP", "museu de arte": "MASP", "paulista": "Trianon-Masp",
    "barra funda": "Palmeiras-Barra Funda", "palmeiras": "Palmeiras-Barra Funda",
    "itaquera": "Corinthians-Itaquera", "arena": "Neo Química Arena",
    "neo quimica": "Neo Química Arena", "neo quimica arena": "Neo Química Arena",
    "liberdade": "Japão-Liberdade", "tiete": "Portuguesa-Tietê",
    "pinacoteca": "Pinacoteca", "hc": "Hospital das Clínicas",
    "clinicas": "Hospital das Clínicas", "ipiranga": "Museu do Ipiranga",
    "teatro": "Theatro Municipal", "theatro": "Theatro Municipal",
    "memorial": "Memorial da América Latina",
    "vila madalena": "Vila Madalena", "jabaquara": "Jabaquara",
}


def resolver_nome(nome):
    if not nome:
        return None
    alvo = normalizar(str(nome)).strip()
    for prefixo in ("📍 ", "🚇 ", "(local) ", "(estacao) ", "(estação) "):
        if alvo.startswith(normalizar(prefixo)):
            alvo = alvo[len(normalizar(prefixo)):].strip()
    for e in ESTACOES_TODAS:
        if normalizar(e) == alvo:
            return ("estacao", e)
    for l in LOCAIS:
        if normalizar(l) == alvo:
            return ("local", l)
    if alvo in ALIAS:
        return resolver_nome(ALIAS[alvo])
    hits = []
    for e in ESTACOES_TODAS:
        if normalizar(e).startswith(alvo) and len(alvo) >= 4:
            hits.append(("estacao", e))
    for l in LOCAIS:
        if normalizar(l).startswith(alvo) and len(alvo) >= 4:
            hits.append(("local", l))
    if len(hits) == 1:
        return hits[0]
    return None


def interpretar_offline(texto):
    tmin, tsem = texto.lower(), normalizar(texto)
    cand = [(n, "e") for n in ESTACOES_TODAS] + [(n, "l") for n in LOCAIS]
    cand.sort(key=lambda c: len(c[0]), reverse=True)
    ocup = [False] * len(tmin)
    achados = []
    for nome, _ in cand:
        buscas = [(tmin, nome.lower())]
        if len(nome) > 4 and len(tsem) == len(tmin):
            buscas.append((tsem, normalizar(nome)))
        for base, pad in buscas:
            for m in re.finditer(r"(?<!\w)" + re.escape(pad) + r"(?!\w)", base):
                if not any(ocup[m.start():m.end()]):
                    achados.append((m.start(), nome))
                    for i in range(m.start(), m.end()):
                        ocup[i] = True
    for alias, oficial in ALIAS.items():
        if len(alias) < 3:
            continue
        for m in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", tsem):
            if not any(ocup[m.start():m.end()]):
                achados.append((m.start(), oficial))
                for i in range(m.start(), min(m.end(), len(ocup))):
                    ocup[i] = True
    for m in re.finditer(r"(?<!\w)se(?!\w)", tsem):
        if m.start() < len(ocup) and not ocup[m.start()]:
            achados.append((m.start(), "Sé"))
    achados.sort()
    pal = ["cadeira de rodas", "acessibilidade", "mobilidade", "muleta", "carrinho de bebe", "elevador"]
    return {
        "origem": achados[0][1] if len(achados) > 0 else None,
        "destino": achados[1][1] if len(achados) > 1 else None,
        "acessibilidade": any(p in tsem for p in pal),
    }


PROMPT_INT = """Você é o módulo de INTERPRETAÇÃO do MetrôBot SP.
Transforme o pedido do passageiro em JSON.
Estações válidas: {estacoes}
Locais válidos: {locais}
Responda APENAS com JSON:
{{"origem":"<nome exato ou null>","destino":"<nome exato ou null>","acessibilidade":<true|false>}}
Regras: use SOMENTE nomes das listas; se não souber, null; nunca invente."""


def interpretar_pedido(texto):
    if PROVEDOR == "offline":
        bruto, fonte = interpretar_offline(texto), "offline"
    else:
        sistema = PROMPT_INT.format(estacoes=", ".join(ESTACOES_TODAS), locais=", ".join(LOCAIS))
        try:
            resp = chamar_llm([{"role": "system", "content": sistema},
                               {"role": "user", "content": texto}], modo_json=True)
            resp = (resp or "").strip()
            if resp.startswith("```"):
                resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp).strip()
            bruto, fonte = json.loads(resp), "Llama (Groq)"
        except Exception:
            bruto, fonte = interpretar_offline(texto), "offline"
    o, d = resolver_nome(bruto.get("origem")), resolver_nome(bruto.get("destino"))
    if o is None or d is None:
        return None, "Não entendi a origem e/ou o destino. Tente algo como: 'Estou na Sé e quero ir ao MASP'."
    return {"origem": o, "destino": d, "acessibilidade": bool(bruto.get("acessibilidade"))}, fonte


PROMPT_NAR = """Você é o NARRADOR do MetrôBot SP. Explique a rota em português, claro e simpático,
em poucas frases. Use SOMENTE os dados do JSON. É OBRIGATÓRIO citar as baldeações do campo
"roteiro_detalhado" (ex.: "Na Sé, troque para a Linha 3-Vermelha"). Se "caminho" for null, diga
que não há rota e cite as bloqueadas. Se houver "alertas", destaque-os. Não invente nada."""


def narrar_offline(r):
    if r["caminho"] is None:
        return (f"Não existe rota de {r['origem']} até {r['destino']} com as estações "
                f"bloqueadas: {', '.join(r['bloqueadas']) or '—'}.")
    t = "Rota:\n" + r["roteiro_detalhado"] + "\n\n"
    t += (f"Total: {r['paradas']} parada(s), {r['qtd_baldeacoes']} baldeação(ões), "
          f"~{r['tempo_min']} min.")
    if r["alertas"]:
        t += "\n⚠️ Atenção: " + "; ".join(r["alertas"]) + "."
    return t


def narrar(r):
    dados = {k: r[k] for k in ("origem", "destino", "caminho", "paradas", "qtd_baldeacoes",
                               "tempo_min", "bloqueadas", "alertas", "roteiro_detalhado")}
    if PROVEDOR == "offline":
        return narrar_offline(r)
    try:
        return chamar_llm([{"role": "system", "content": PROMPT_NAR},
                           {"role": "user", "content": json.dumps(dados, ensure_ascii=False)}])
    except Exception:
        return narrar_offline(r)


# ============================================================ TEMAS
TEMAS = {
    "escuro": {
        "bg": "#121212", "panel": "#1c1c1c", "card": "#262626",
        "txt": "#f3f3f0", "muted": "#9a9a96", "canvas": "#161616",
        "track": "#333333", "accent": "#ff6b00", "chip": "#2e2e2e",
        "user": "#ffb37a", "route": "#ffb020", "ok": "#4ade80",
        "warn": "#fbbf24", "legend_bg": "#1c1c1c", "title_bg": "#1c1c1c",
        "sel": "#333333", "bubble_user": "#2a2118", "bubble_bot": "#262626",
    },
    "claro": {
        "bg": "#f6f6f4", "panel": "#ffffff", "card": "#f0f0ee",
        "txt": "#1c1c1a", "muted": "#8a8a86", "canvas": "#fafaf8",
        "track": "#e4e4e0", "accent": "#1a1a1a", "chip": "#ecece8",
        "user": "#1a1a1a", "route": "#b45309", "ok": "#15803d",
        "warn": "#b45309", "legend_bg": "#ffffff", "title_bg": "#ffffff",
        "sel": "#ecece8", "bubble_user": "#1a1a1a", "bubble_bot": "#f0f0ee",
    },
}


def _carregar_tema():
    try:
        with open(os.path.join(_base_dir(), ".metrobot_tema"), "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t in TEMAS:
                return t
    except Exception:
        pass
    return "claro"


def _salvar_tema(nome):
    try:
        with open(os.path.join(_base_dir(), ".metrobot_tema"), "w", encoding="utf-8") as f:
            f.write(nome)
    except Exception:
        pass


# ============================================================ INTERFACE (Tkinter)
class MetroBotApp:
    def __init__(self, root):
        self.root = root
        self.tema_nome = _carregar_tema()
        self.t = TEMAS[self.tema_nome]
        self.resultado = None
        self._ocupado = False
        self._themed = []

        root.title("MetrôBot SP")
        root.geometry("1320x840")
        root.minsize(1100, 700)

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.topbar = tk.Frame(root, height=58)
        self.topbar.pack(side="top", fill="x")
        self.topbar.pack_propagate(False)
        self.lbl_titulo = tk.Label(self.topbar, text="MetrôBot",
                                   font=("Segoe UI", 16, "bold"))
        self.lbl_titulo.pack(side="left", padx=22)
        self.lbl_sub = tk.Label(self.topbar, text="São Paulo  ·  Linhas 1 · 2 · 3",
                                font=("Segoe UI", 9))
        self.lbl_sub.pack(side="left")
        self.btn_tema = tk.Button(
            self.topbar, command=self.alternar_tema, relief="flat",
            font=("Segoe UI", 9), padx=12, pady=6, cursor="hand2")
        self.btn_tema.pack(side="right", padx=16)
        self.status = tk.Label(self.topbar, text="", font=("Segoe UI", 8), cursor="hand2")
        self.status.pack(side="right", padx=8)
        self.status.bind("<Button-1>", lambda e: self.configurar_chave())

        body = tk.Frame(root)
        body.pack(side="top", fill="both", expand=True)
        self.body = body

        self.left = tk.Frame(body, width=440)
        self.left.pack(side="left", fill="both")
        self.left.pack_propagate(False)
        self.right = tk.Frame(body)
        self.right.pack(side="left", fill="both", expand=True)

        self.head = tk.Frame(self.left)
        self.head.pack(fill="x", padx=18, pady=(14, 2))
        self.lbl_chat = tk.Label(self.head, text="Conversa", font=("Segoe UI", 11, "bold"))
        self.lbl_chat.pack(anchor="w")

        # Listas origem / destino
        self.box_listas = tk.Frame(self.left)
        self.box_listas.pack(fill="x", padx=18, pady=(4, 8))
        self.lbl_listas = tk.Label(self.box_listas, text="Escolher estações",
                                   font=("Segoe UI", 8, "bold"))
        self.lbl_listas.pack(anchor="w", pady=(0, 4))

        row_od = tk.Frame(self.box_listas)
        row_od.pack(fill="x")
        col_o = tk.Frame(row_od)
        col_o.pack(side="left", fill="x", expand=True)
        col_d = tk.Frame(row_od)
        col_d.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.lbl_origem = tk.Label(col_o, text="Origem", font=("Segoe UI", 8))
        self.lbl_origem.pack(anchor="w")
        self.dd_origem = ttk.Combobox(col_o, values=OPCAO_ROTULOS, state="normal",
                                      font=("Segoe UI", 9), width=22)
        self.dd_origem.set(ROTULO_POR_VALOR[("estacao", "Sé")])
        self.dd_origem.pack(fill="x", pady=(2, 0))
        self.lbl_destino = tk.Label(col_d, text="Destino", font=("Segoe UI", 8))
        self.lbl_destino.pack(anchor="w")
        self.dd_destino = ttk.Combobox(col_d, values=OPCAO_ROTULOS, state="normal",
                                       font=("Segoe UI", 9), width=22)
        self.dd_destino.set(ROTULO_POR_VALOR[("local", "MASP")])
        self.dd_destino.pack(fill="x", pady=(2, 0))

        row_btns = tk.Frame(self.box_listas)
        row_btns.pack(fill="x", pady=(8, 0))
        self.btn_swap = tk.Button(row_btns, text="⇄ Trocar", command=self.trocar_od,
                                  relief="flat", font=("Segoe UI", 9), padx=10, pady=5,
                                  cursor="hand2")
        self.btn_swap.pack(side="left")
        self.btn_tracar = tk.Button(row_btns, text="Traçar rota", command=self.tracar_listas,
                                    relief="flat", font=("Segoe UI", 10, "bold"),
                                    padx=14, pady=5, cursor="hand2", fg="white")
        self.btn_tracar.pack(side="right")

        # Opções
        self.opts = tk.Frame(self.left)
        self.opts.pack(fill="x", padx=18, pady=(0, 4))
        self.algo = tk.StringVar(value="BFS")
        self.rb_bfs = tk.Radiobutton(self.opts, text="BFS", variable=self.algo, value="BFS",
                                     font=("Segoe UI", 9))
        self.rb_dfs = tk.Radiobutton(self.opts, text="DFS", variable=self.algo, value="DFS",
                                     font=("Segoe UI", 9))
        self.rb_bfs.pack(side="left")
        self.rb_dfs.pack(side="left")
        self.acess = tk.BooleanVar()
        self.pico = tk.BooleanVar()
        self.chk_acess = tk.Checkbutton(self.opts, text="Acessibilidade", variable=self.acess,
                                        font=("Segoe UI", 9))
        self.chk_pico = tk.Checkbutton(self.opts, text="Pico", variable=self.pico,
                                       font=("Segoe UI", 9))
        self.chk_acess.pack(side="left", padx=6)
        self.chk_pico.pack(side="left")

        self.cen = tk.Frame(self.left)
        self.cen.pack(fill="x", padx=18, pady=(0, 6))
        self.lbl_fechada = tk.Label(self.cen, text="Fechar estação", font=("Segoe UI", 8))
        self.lbl_fechada.pack(side="left")
        self.fechada = ttk.Combobox(self.cen, values=["(nenhuma)"] + ESTACOES_TODAS,
                                    state="readonly", width=22, font=("Segoe UI", 9))
        self.fechada.current(0)
        self.fechada.pack(side="left", padx=6, fill="x", expand=True)

        # Histórico da conversa (não come o espaço do campo de texto)
        self.chat = scrolledtext.ScrolledText(
            self.left, font=("Segoe UI", 10), wrap="word",
            relief="flat", bd=0, padx=12, pady=10, state="disabled", height=8)
        self.chat.pack(fill="both", expand=True, padx=18, pady=(6, 0))
        self.chat.bind("<Button-1>", lambda e: self.entry.focus_set())

        self.composer = tk.Frame(self.left)
        self.composer.pack(fill="x", padx=22, pady=(12, 16))
        self.entry_row = tk.Frame(self.composer)
        self.entry_row.pack(fill="x")

        self.lbl_digite = tk.Label(self.entry_row, text="Digite aqui o seu pedido",
                                   font=("Segoe UI", 12, "bold"), justify="center")
        self.lbl_digite.pack(pady=(0, 10))
        self.entry = tk.Text(self.entry_row, height=4, wrap="word", font=("Segoe UI", 13),
                             relief="solid", bd=1, padx=14, pady=12, undo=True)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", self._enter_enviar)

        self.chips = tk.Frame(self.entry_row)
        self.chips.pack(fill="x", pady=(10, 8))
        self.chip_btns = []
        for frase in (
            "Estou na Sé e quero ir ao MASP",
            "Vila Madalena até Jabaquara",
            "Barra Funda até a Neo Química Arena",
        ):
            b = tk.Button(
                self.chips, text=frase, command=lambda f=frase: self.enviar_sugestao(f),
                relief="flat", font=("Segoe UI", 8), wraplength=130, justify="center",
                padx=8, pady=6, cursor="hand2")
            b.pack(side="left", padx=3, fill="x", expand=True)
            self.chip_btns.append(b)

        self.btn_enviar = tk.Button(self.entry_row, text="Enviar pedido", command=self.enviar,
                                    relief="flat", font=("Segoe UI", 12, "bold"),
                                    padx=24, pady=10, fg="white", cursor="hand2")
        self.btn_enviar.pack(pady=(4, 0))

        # Direita: mapa oculto até haver rota
        self.kpis = tk.Frame(self.right)
        self._make_kpis()
        self.canvas = tk.Canvas(self.right, highlightthickness=0)
        self.canvas.bind("<Configure>", lambda e: self.desenhar_mapa())
        self.placeholder = tk.Frame(self.right)
        self.ph_titulo = tk.Label(self.placeholder, text="O mapa aparece aqui",
                                  font=("Segoe UI", 16, "bold"))
        self.ph_titulo.pack(pady=(80, 8))
        self.ph_txt = tk.Label(
            self.placeholder,
            text="Digite no chat ou escolha origem e destino.\n"
                 "Quando a rota for encontrada, só o trecho da viagem é desenhado.",
            font=("Segoe UI", 10), justify="center")
        self.ph_txt.pack()
        self.placeholder.pack(fill="both", expand=True)
        self._mapa_visivel = False

        self._aplicar_tema()
        self._atualizar_status()
        self._saudacao()
        self.entry.focus_set()

    # -------------------------------------------------- Tema
    def alternar_tema(self):
        self.tema_nome = "claro" if self.tema_nome == "escuro" else "escuro"
        _salvar_tema(self.tema_nome)
        self._aplicar_tema()
        self.desenhar_mapa()

    def _aplicar_tema(self):
        t = TEMAS[self.tema_nome]
        self.t = t
        self.root.configure(bg=t["bg"])
        for w, key in (
            (self.topbar, "panel"), (self.body, "bg"),
            (self.left, "panel"), (self.right, "bg"), (self.head, "panel"),
            (self.box_listas, "panel"), (self.opts, "panel"), (self.cen, "panel"),
            (self.chips, "panel"), (self.entry_row, "panel"), (self.composer, "panel"),
            (self.kpis, "bg"), (self.placeholder, "bg"),
        ):
            w.configure(bg=t[key])
        def _pintar(fr, cor):
            for child in fr.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=cor)
                    _pintar(child, cor)
        _pintar(self.topbar, t["panel"])
        _pintar(self.head, t["panel"])
        _pintar(self.box_listas, t["panel"])
        _pintar(self.opts, t["panel"])
        _pintar(self.cen, t["panel"])
        _pintar(self.composer, t["panel"])
        _pintar(self.chips, t["panel"])
        _pintar(self.entry_row, t["panel"])
        _pintar(self.placeholder, t["bg"])
        self.lbl_titulo.configure(bg=t["panel"], fg=t["txt"])
        self.lbl_sub.configure(bg=t["panel"], fg=t["muted"])
        self.lbl_chat.configure(bg=t["panel"], fg=t["txt"])
        self.status.configure(bg=t["panel"])
        self.lbl_listas.configure(bg=t["panel"], fg=t["muted"])
        self.lbl_origem.configure(bg=t["panel"], fg=t["muted"])
        self.lbl_destino.configure(bg=t["panel"], fg=t["muted"])
        self.lbl_fechada.configure(bg=t["panel"], fg=t["muted"])
        self.lbl_digite.configure(bg=t["panel"], fg=t["txt"], justify="center")
        self.ph_titulo.configure(bg=t["bg"], fg=t["txt"])
        self.ph_txt.configure(bg=t["bg"], fg=t["muted"])
        self.placeholder.configure(bg=t["bg"])
        for rb in (self.rb_bfs, self.rb_dfs, self.chk_acess, self.chk_pico):
            rb.configure(bg=t["panel"], fg=t["txt"], selectcolor=t["card"],
                         activebackground=t["panel"], activeforeground=t["txt"])
        self.btn_tema.configure(
            text="Claro" if self.tema_nome == "escuro" else "Escuro",
            bg=t["card"], fg=t["txt"], activebackground=t["chip"], activeforeground=t["txt"])
        self.btn_swap.configure(bg=t["card"], fg=t["txt"],
                                activebackground=t["chip"], activeforeground=t["txt"])
        fg_btn = "#ffffff" if self.tema_nome == "escuro" else "#ffffff"
        ac_bg = "#e05f00" if self.tema_nome == "escuro" else "#333333"
        self.btn_tracar.configure(bg=t["accent"], fg=fg_btn, activebackground=ac_bg)
        self.btn_enviar.configure(bg=t["accent"], fg=fg_btn, activebackground=ac_bg)
        self.entry.configure(bg=t["card"], fg=t["txt"], insertbackground=t["txt"],
                             highlightthickness=1, highlightbackground=t["track"],
                             highlightcolor=t["accent"])
        self.chat.configure(bg=t["card"], fg=t["txt"])
        self.chat.tag_config("user", foreground=t["user"], font=("Segoe UI", 10, "bold"),
                             lmargin1=8, lmargin2=8, rmargin=8, spacing1=4, spacing3=8)
        self.chat.tag_config("bot", foreground=t["txt"],
                             lmargin1=8, lmargin2=8, rmargin=8, spacing1=2, spacing3=8)
        self.chat.tag_config("sys", foreground=t["muted"], font=("Segoe UI", 9, "italic"),
                             lmargin1=8, spacing3=4)
        self.chat.tag_config("route", foreground=t["route"], font=("Segoe UI", 10),
                             lmargin1=16, lmargin2=16, spacing3=8)
        for b in self.chip_btns:
            b.configure(bg=t["card"], fg=t["muted"],
                        activebackground=t["chip"], activeforeground=t["txt"])
        self.canvas.configure(bg=t["canvas"])
        for card, val, lab, _cor in self.kpi_cards:
            card.configure(bg=t["card"])
            val.configure(bg=t["card"], fg=t["txt"])
            lab.configure(bg=t["card"], fg=t["muted"])
        self.style.configure("TCombobox", fieldbackground=t["card"], background=t["card"],
                             foreground=t["txt"], arrowcolor=t["txt"])
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", t["card"]), ("!disabled", t["card"])],
                       foreground=[("readonly", t["txt"]), ("!disabled", t["txt"])],
                       selectbackground=[("readonly", t["sel"]), ("!disabled", t["sel"])],
                       selectforeground=[("readonly", t["txt"]), ("!disabled", t["txt"])])
        self._atualizar_status()

    # -------------------------------------------------- KPIs
    def _make_kpis(self):
        self.kpi_vals = {}
        self.kpi_cards = []
        specs = [("Paradas", "#0a6ed1"), ("Baldeações", "#e2312d"),
                 ("Tempo", "#1e9e58"), ("Visitadas", "#8a93a6")]
        for nome, cor in specs:
            c = tk.Frame(self.kpis, highlightthickness=0)
            c.pack(side="left", expand=True, fill="x", padx=4)
            bar = tk.Frame(c, bg=cor, height=3)
            bar.pack(fill="x")
            v = tk.Label(c, text="—", font=("Segoe UI", 20, "bold"))
            v.pack(anchor="w", padx=12, pady=(8, 0))
            lab = tk.Label(c, text=nome.upper(), font=("Segoe UI", 8))
            lab.pack(anchor="w", padx=12, pady=(0, 10))
            self.kpi_vals[nome] = v
            self.kpi_cards.append((c, v, lab, cor))

    def _set_kpis(self, r):
        if not r or r["caminho"] is None:
            for v in self.kpi_vals.values():
                v.config(text="—")
            return
        self.kpi_vals["Paradas"].config(text=str(r["paradas"]))
        self.kpi_vals["Baldeações"].config(text=str(r["qtd_baldeacoes"]))
        self.kpi_vals["Tempo"].config(text=f"~{r['tempo_min']}′")
        self.kpi_vals["Visitadas"].config(text=str(len(r["visitados"])))

    # -------------------------------------------------- Chat helpers
    def _add(self, texto, tag="bot", prefixo=""):
        self.chat.config(state="normal")
        if prefixo:
            self.chat.insert("end", prefixo, tag)
        self.chat.insert("end", texto + "\n\n", tag)
        self.chat.see("end")
        self.chat.config(state="disabled")

    def _texto_pedido(self):
        return self.entry.get("1.0", "end").strip()

    def _limpar_pedido(self):
        self.entry.delete("1.0", "end")

    def _enter_enviar(self, evento=None):
        if evento is not None and (evento.state & 0x0001):
            return None
        self.enviar()
        return "break"

    def _saudacao(self):
        self._add("Olá! Sou o MetrôBot.\n"
                  "Escreva no campo do meio, por exemplo: "
                  "“Estou na Vila Madalena e quero ir ao MASP”.\n"
                  "Ou escolha origem e destino nas listas e clique em Traçar rota.\n"
                  "O mapa só aparece depois, mostrando só o trecho da viagem.",
                  "bot", "MetrôBot: ")

    def _contexto(self):
        return {
            "acess": self.acess.get(),
            "pico": self.pico.get(),
            "algo": self.algo.get(),
            "fechadas": [] if self.fechada.get() == "(nenhuma)" else [self.fechada.get()],
        }

    def _set_ocupado(self, ocupado):
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        self.btn_enviar.configure(state=estado, text="Buscando…" if ocupado else "Enviar pedido")
        self.btn_tracar.configure(state=estado)

    def _atualizar_status(self):
        ok, motivo = llm_disponivel()
        if ok:
            self.status.config(text=f"● IA online — {motivo}", fg=self.t["ok"])
        else:
            self.status.config(text=f"● Modo offline ({motivo}) — clique para configurar a chave",
                               fg=self.t["warn"])

    def configurar_chave(self):
        chave = simpledialog.askstring("Configurar Groq",
                                       "Cole sua GROQ_API_KEY (gsk_...):", show="*", parent=self.root)
        if chave:
            try:
                with open(os.path.join(_base_dir(), ".env"), "w", encoding="utf-8") as f:
                    f.write(f"GROQ_API_KEY={chave.strip()}\n")
                os.environ["GROQ_API_KEY"] = chave.strip()
                global PROVEDOR
                PROVEDOR = "groq"
                messagebox.showinfo("Pronto", "Chave salva! A IA está online.", parent=self.root)
                self._atualizar_status()
            except Exception as e:
                messagebox.showerror("Erro", str(e), parent=self.root)

    def enviar_sugestao(self, texto):
        self._limpar_pedido()
        self.entry.insert("1.0", texto)
        self.enviar()

    def trocar_od(self):
        a, b = self.dd_origem.get(), self.dd_destino.get()
        self.dd_origem.set(b)
        self.dd_destino.set(a)

    def _sincronizar_listas(self, pedido):
        if not pedido:
            return
        if pedido["origem"] in ROTULO_POR_VALOR:
            self.dd_origem.set(ROTULO_POR_VALOR[pedido["origem"]])
        if pedido["destino"] in ROTULO_POR_VALOR:
            self.dd_destino.set(ROTULO_POR_VALOR[pedido["destino"]])

    def _resolver_opcao(self, texto):
        texto = (texto or "").strip()
        if texto in OPCAO_POR_ROTULO:
            return OPCAO_POR_ROTULO[texto]
        limpo = texto.replace("📍 ", "").replace("🚇 ", "").strip()
        return resolver_nome(limpo)

    def tracar_listas(self):
        if self._ocupado:
            return
        o = self._resolver_opcao(self.dd_origem.get())
        d = self._resolver_opcao(self.dd_destino.get())
        if not o or not d:
            messagebox.showinfo("MetrôBot", "Digite ou escolha origem e destino.", parent=self.root)
            return
        if o == d:
            messagebox.showinfo("MetrôBot", "Origem e destino precisam ser diferentes.", parent=self.root)
            return
        self._add(f"{o[1]} → {d[1]}", "user", "Você: ")
        self._add("traçando a rota…", "sys")
        pedido = {"origem": o, "destino": d, "acessibilidade": self.acess.get()}
        ctx = self._contexto()
        self._set_ocupado(True)
        threading.Thread(target=self._calcular, args=(pedido, "listas", ctx), daemon=True).start()

    # -------------------------------------------------- Fluxo principal
    def enviar(self):
        if self._ocupado:
            return
        texto = self._texto_pedido()
        if not texto:
            return
        self._limpar_pedido()
        self._add(texto, "user", "Você: ")
        self._add("pensando…", "sys")
        ctx = self._contexto()
        self._set_ocupado(True)
        threading.Thread(target=self._processar, args=(texto, ctx), daemon=True).start()

    def _processar(self, texto, ctx):
        try:
            pedido, fonte = interpretar_pedido(texto)
        except Exception as e:
            pedido, fonte = None, str(e)
        if pedido is None:
            self.root.after(0, lambda: self._fim_erro(fonte))
            return
        if pedido["origem"] == pedido["destino"]:
            self.root.after(0, lambda: self._fim_erro(
                "Origem e destino são o mesmo lugar. Escolha outro destino."))
            return
        pedido["acessibilidade"] = pedido["acessibilidade"] or ctx["acess"]
        self._calcular(pedido, fonte, ctx)

    def _calcular(self, pedido, fonte, ctx):
        try:
            r = planejar(pedido, fechadas=ctx["fechadas"], pico=ctx["pico"],
                         algoritmo=ctx["algo"])
            texto_nar = narrar(r)
        except Exception as e:
            msg = f"Não consegui calcular a rota. {e}"
            self.root.after(0, lambda m=msg: self._fim_erro(m))
            return
        self.root.after(0, lambda: self._mostrar_resultado(pedido, fonte, r, texto_nar))

    def _fim_erro(self, msg):
        self._set_ocupado(False)
        self._add(msg, "bot", "MetrôBot: ")

    def _mostrar_resultado(self, pedido, fonte, r, texto_nar):
        self._set_ocupado(False)
        self._sincronizar_listas(pedido)
        self.resultado = r
        self._set_kpis(r)
        self._mostrar_mapa(bool(r.get("caminho")))
        self.desenhar_mapa()
        self._add(f"(via {fonte})", "sys")
        self._add(texto_nar, "bot", "MetrôBot: ")
        if r.get("caminho"):
            self._add(r["roteiro_detalhado"], "route")
        self.entry.focus_set()

    def _mostrar_mapa(self, visivel):
        if visivel and not self._mapa_visivel:
            self.placeholder.pack_forget()
            self.kpis.pack(fill="x", padx=16, pady=(14, 8))
            self.canvas.pack(fill="both", expand=True, padx=16, pady=(0, 16))
            self._mapa_visivel = True
        elif not visivel and self._mapa_visivel:
            self.kpis.pack_forget()
            self.canvas.pack_forget()
            self.placeholder.pack(fill="both", expand=True)
            self._mapa_visivel = False
        if not visivel and self.resultado is not None:
            self.ph_titulo.config(text="Sem rota neste pedido")
            self.ph_txt.config(text="Tente outro destino ou libere a estação fechada.")
        elif not visivel:
            self.ph_titulo.config(text="O mapa aparece aqui")
            self.ph_txt.config(text="Digite no campo do meio ou escolha origem e destino.")

    # -------------------------------------------------- Desenho do mapa
    def _pos_rotulo(self, x, y, lado, dist=16):
        d = {
            "w":  (x - dist, y, "e"),
            "e":  (x + dist, y, "w"),
            "n":  (x, y - dist, "s"),
            "s":  (x, y + dist, "n"),
            "nw": (x - dist, y - 11, "e"),
            "ne": (x + dist, y - 11, "w"),
            "sw": (x - dist, y + 11, "e"),
            "se": (x + dist, y + 11, "w"),
        }
        return d.get(lado, (x + dist, y, "w"))

    def desenhar_mapa(self):
        cv = self.canvas
        cv.delete("all")
        if not self._mapa_visivel:
            return
        t = self.t
        W = max(cv.winfo_width() or 780, 200)
        H = max(cv.winfo_height() or 640, 200)
        r = self.resultado
        cam = (r or {}).get("caminho") or []
        if not cam:
            return

        origem, destino = r["origem"], r["destino"]
        bald = {e for e, _ in r["baldeacoes"]}
        n = len(cam)
        mL, mR, mT, mB = 70, 40, 56, 46
        usable_w = max(W - mL - mR, 80)
        y = H * 0.52

        pts = []
        for i in range(n):
            x = mL + (usable_w * i / max(n - 1, 1))
            pts.append((x, y))

        for i in range(n - 1):
            a, b = cam[i], cam[i + 1]
            linhas = sorted(LINHAS_TRECHO.get((a, b), {"Linha 1-Azul"}))
            cor = CORES[linhas[0]]
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            cv.create_line(x1, y1, x2, y2, fill=t["track"], width=16,
                           capstyle="round")
            cv.create_line(x1, y1, x2, y2, fill=cor, width=8, capstyle="round")

        for i, est in enumerate(cam):
            x, yy = pts[i]
            if est == origem:
                self._dot(cv, x, yy, 11, "#0a6ed1", t["canvas"], w=3)
                cv.create_text(x, yy, text="A", fill="white", font=("Segoe UI", 8, "bold"))
            elif est == destino:
                self._dot(cv, x, yy, 11, "#16a34a", t["canvas"], w=3)
                cv.create_text(x, yy, text="B", fill="white", font=("Segoe UI", 8, "bold"))
            elif est in bald:
                self._dot(cv, x, yy, 9, t["canvas"], "#e2312d", w=3)
            else:
                self._dot(cv, x, yy, 6, t["canvas"], "#f5c542", w=2)
            acima = (i % 2 == 0)
            nome = est if est in (origem, destino) or est in bald or n <= 10 else nome_mapa(est)
            fonte = ("Segoe UI", 9, "bold") if est in (origem, destino) or est in bald else ("Segoe UI", 8)
            cv.create_text(x, yy + (-22 if acima else 22), text=nome,
                           fill=t["txt"], font=fonte, anchor="s" if acima else "n",
                           angle=0 if n <= 12 else 40)

        cv.create_text(24, 22, text=f"{origem}   →   {destino}",
                       fill=t["txt"], font=("Segoe UI", 13, "bold"), anchor="w")
        lx = 24
        for cor, txt in (("#0a6ed1", "origem"), ("#16a34a", "destino"),
                         ("#f5c542", "rota"), ("#e2312d", "baldeação")):
            cv.create_oval(lx, H - 26, lx + 8, H - 18, fill=cor, outline="")
            cv.create_text(lx + 12, H - 22, text=txt, fill=t["muted"],
                           font=("Segoe UI", 8), anchor="w")
            lx += 100

    def _dot(self, cv, x, y, r, fill, outline, w=2):
        cv.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline=outline, width=w)


def main():
    root = tk.Tk()
    try:
        # detecta LLM e ajusta provedor global se não houver
        ok, _ = llm_disponivel()
        global PROVEDOR
        if not ok:
            PROVEDOR = "offline"
    except Exception:
        pass
    MetroBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
