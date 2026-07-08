"""rulers.py — réguas DETERMINÍSTICAS reutilizáveis (o fiscal precisa de uma por papel).

`role_shadow`, `candidate_eval` e `bench` pedem uma régua determinística por papel: a peça
que compara, DE GRAÇA e SEM MODELO, a saída paga contra um critério objetivo (ou contra o
gold humano). O repo até hoje não trazia nenhuma pronta — cada adotante reescrevia a sua. Este
módulo entrega as comuns, pra baixar a barreira de rodar o regime de medição.

Contrato de uma régua:  `ruler(text: str, gold: object | None = None) -> dict`
com pelo menos `{"pass": bool, "label": str}` e, quando fizer sentido, `{"score": float,
"detail": ...}`. Em uso normal NUNCA levanta pro chamador (entrada estranha -> pass=False) —
e o motor que a chama já é fail-soft de qualquer jeito.

INVARIANTES (mesma metodologia do resto do pacote):
- É uma RÉGUA objetiva/determinística, não um modelo julgando outro modelo (anti-autofagia, D6).
- Só emite um veredito; NÃO promove modelo, NÃO reescreve roster (D5). Isso é decisão humana.

STDLIB-ONLY (D2). PURO (sem rede, sem arquivo) -> 100% testável hermético.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Callable, Optional, Sequence

from .squad import parse_verdict_keyword  # bridge: régua de verdito por palavra-chave

Ruler = Callable[[str, object], dict]

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\n(.*)\n```\s*$", re.DOTALL)
# casa números pt-BR/en: 1.050 · 2.250 · 37,5 · 0.25 · -3 (com separador de milhar e decimal).
_NUM_RE = re.compile(r"-?\d[\d.,]*")


def _strip_one_fence(text: str) -> str:
    """Remove UMA cerca ```lang\\n...\\n``` que envolva o texto inteiro (mesma defesa do
    code_writer). Cerca no meio do texto fica intacta."""
    t = (text or "").strip()
    m = _FENCE_RE.match(t)
    return m.group(1) if m else t


def _norm(s: object) -> str:
    """Normaliza p/ comparação tolerante: sem acento, minúsculo, espaço colapsado, aparado."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.strip().lower())


def _parse_number(tok: str) -> Optional[float]:
    """'1.050' -> 1050.0 · '37,5' -> 37.5 · '2.287,50' -> 2287.5 · '0.25' -> 0.25. Heurística
    pt-BR/en de separador; ilegível -> None."""
    tok = tok.strip().strip(".,")
    if not tok:
        return None
    if "." in tok and "," in tok:            # 2.287,50 -> ponto=milhar, vírgula=decimal
        tok = tok.replace(".", "").replace(",", ".")
    elif "," in tok:                          # 37,5 -> vírgula decimal
        tok = tok.replace(",", ".")
    elif tok.count(".") >= 1:                 # ambíguo: '.' é milhar se grupos de 3 dígitos
        parts = tok.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and parts[0].isdigit():
            tok = "".join(parts)
    try:
        return float(tok)
    except ValueError:
        return None


def _all_numbers(text: str) -> "list[float]":
    out: list = []
    for m in _NUM_RE.finditer(text or ""):
        v = _parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


# ── Réguas ───────────────────────────────────────────────────────────────────

def json_valid_ruler(required_keys: "Sequence[str]" = (), *, allow_fenced: bool = False) -> Ruler:
    """Passa se o texto é JSON PARSEÁVEL (objeto) contendo `required_keys`. Por default é
    ESTRITO: um wrapper ```json ... ``` reprova (recompensa 'só JSON' — pega o hábito de cercar
    do DeepSeek et al.). `allow_fenced=True` remove a cerca antes de parsear (leniente)."""
    keys = tuple(required_keys)

    def ruler(text: str, gold: object = None) -> dict:
        raw = (text or "").strip()
        candidate = _strip_one_fence(raw) if allow_fenced else raw
        try:
            obj = json.loads(candidate)
        except Exception:  # noqa: BLE001 — parse falho é o veredito, não um erro do fiscal
            return {"pass": False, "label": "INVALID_JSON"}
        if not isinstance(obj, dict):
            return {"pass": False, "label": "NOT_OBJECT"}
        missing = [k for k in keys if k not in obj]
        if missing:
            return {"pass": False, "label": "MISSING_KEYS", "detail": {"missing": missing}}
        return {"pass": True, "label": "VALID",
                "detail": {"fenced": candidate != raw, "keys": list(obj.keys())}}

    return ruler


def numeric_close_ruler(tol: float = 0.01, *, relative: bool = False) -> Ruler:
    """Passa se ALGUM número extraído do texto está a `tol` do `gold` (absoluto; `relative=True`
    usa |gold|*tol). Útil p/ conferir a RESPOSTA numérica de um raciocínio ('...= 1050 grafts')
    sem exigir formato. Sem gold -> pass=False (a régua precisa do alvo humano)."""
    def ruler(text: str, gold: object = None) -> dict:
        if gold is None:
            return {"pass": False, "label": "NO_GOLD"}
        g = _parse_number(str(gold)) if not isinstance(gold, (int, float)) else float(gold)
        if g is None:
            return {"pass": False, "label": "BAD_GOLD"}
        nums = _all_numbers(text)
        thr = abs(g) * tol if relative else tol
        for n in nums:
            if abs(n - g) <= thr:
                return {"pass": True, "label": "MATCH", "score": n,
                        "detail": {"matched": n, "gold": g}}
        return {"pass": False, "label": "NO_MATCH", "detail": {"gold": g, "found": nums[:8]}}

    return ruler


def length_window_ruler(min_words: int, max_words: int) -> Ruler:
    """Passa se a contagem de palavras cai em [min, max]. Objetivo p/ 'redação de 220–280
    palavras' e afins (o benchmark mostrou modelos entregando curto — isto mede isso de graça)."""
    def ruler(text: str, gold: object = None) -> dict:
        w = len((text or "").split())
        ok = min_words <= w <= max_words
        label = "IN_WINDOW" if ok else ("TOO_SHORT" if w < min_words else "TOO_LONG")
        return {"pass": ok, "label": label, "score": w,
                "detail": {"words": w, "window": [min_words, max_words]}}

    return ruler


def contains_all_ruler(substrings: "Sequence[str]", *, strip_accents: bool = True) -> Ruler:
    """Passa se TODAS as `substrings` aparecem no texto (comparação sem acento/caixa por
    default). Útil p/ 'o texto cita as 5 posições de foto?' — cobertura de requisitos."""
    def ruler(text: str, gold: object = None) -> dict:
        hay = _norm(text) if strip_accents else (text or "").lower()
        norm = (lambda s: _norm(s)) if strip_accents else (lambda s: s.lower())
        missing = [s for s in substrings if norm(s) not in hay]
        return {"pass": not missing,
                "label": "ALL_PRESENT" if not missing else "MISSING",
                "detail": {"missing": missing}}

    return ruler


def exact_match_ruler(*, normalize: bool = True) -> Ruler:
    """Passa se o texto == gold (normalizado por default: sem acento/caixa/espaço extra)."""
    def ruler(text: str, gold: object = None) -> dict:
        if gold is None:
            return {"pass": False, "label": "NO_GOLD"}
        a = _norm(text) if normalize else (text or "").strip()
        b = _norm(gold) if normalize else str(gold).strip()
        ok = a == b
        return {"pass": ok, "label": "MATCH" if ok else "MISMATCH"}

    return ruler


def keyword_verdict_ruler(keywords: "Sequence[str]" = ("GOOD", "OK", "BAD"),
                          default: str = "BAD") -> Ruler:
    """Extrai o veredito por palavra (usa `squad.parse_verdict_keyword` — 1ª keyword por
    word-boundary, empate conservador). Sem gold: `pass=True` e reporta o `label`. Com gold:
    `pass = (label == gold)`. Ponte p/ auditar papéis de JUIZ com a mesma régua do painel."""
    kws = tuple(keywords)

    def ruler(text: str, gold: object = None) -> dict:
        label = parse_verdict_keyword(text, keywords=kws, default=default)
        ok = True if gold is None else (label == str(gold).upper())
        return {"pass": ok, "label": label, "detail": {"gold": gold}}

    return ruler


def set_f1_ruler(threshold: float = 1.0, *, splitter: str = r"[\n,;]+") -> Ruler:
    """Trata texto e gold como CONJUNTOS de itens (split por `splitter`, normalizados) e passa
    se F1 >= threshold. Útil p/ extração de lista ('quais áreas de queixa?'). Reporta P/R/F1."""
    def _toks(x) -> set:
        seq = x if isinstance(x, (list, tuple, set)) else re.split(splitter, str(x or ""))
        return {t for t in (_norm(i) for i in seq) if t}

    def ruler(text: str, gold: object = None) -> dict:
        if gold is None:
            return {"pass": False, "label": "NO_GOLD"}
        pred, goldset = _toks(text), _toks(gold)
        if not goldset:
            return {"pass": False, "label": "EMPTY_GOLD"}
        tp = len(pred & goldset)
        prec = tp / len(pred) if pred else 0.0
        rec = tp / len(goldset)
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        return {"pass": f1 >= threshold, "label": f"F1_{f1:.2f}", "score": round(f1, 4),
                "detail": {"precision": round(prec, 4), "recall": round(rec, 4)}}

    return ruler


# ── Resolvedor por string (p/ o CLI do bench, que lê suites em JSON) ──────────

def resolve_ruler(spec: "Optional[str]") -> "Optional[Ruler]":
    """Mapeia uma string de suite JSON -> régua. `None`/vazio -> None (célula vira human-review).
    Formas: `json_valid` | `json_valid:sexo,idade` · `numeric_close` | `numeric_close:0.01` ·
    `length_window:220:280` · `contains_all:frontal,topo,coroa` · `exact_match` ·
    `keyword_verdict` | `keyword_verdict:GOOD,OK,BAD` · `set_f1` | `set_f1:0.8`."""
    if not spec:
        return None
    name, _, arg = spec.partition(":")
    name = name.strip()
    if name == "json_valid":
        return json_valid_ruler(tuple(k.strip() for k in arg.split(",") if k.strip()))
    if name == "numeric_close":
        return numeric_close_ruler(float(arg) if arg else 0.01)
    if name == "length_window":
        lo, _, hi = arg.partition(":")
        return length_window_ruler(int(lo), int(hi))
    if name == "contains_all":
        return contains_all_ruler(tuple(s.strip() for s in arg.split(",") if s.strip()))
    if name == "exact_match":
        return exact_match_ruler()
    if name == "keyword_verdict":
        kws = tuple(k.strip().upper() for k in arg.split(",") if k.strip()) or ("GOOD", "OK", "BAD")
        return keyword_verdict_ruler(kws)
    if name == "set_f1":
        return set_f1_ruler(float(arg) if arg else 1.0)
    raise ValueError(f"régua desconhecida: {spec!r}")
