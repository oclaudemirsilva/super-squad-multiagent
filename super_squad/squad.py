"""Super Squad Multiagent — o motor da frota (fan-out orquestrado sobre workers heterogêneos).

`run_squad` roda N jobs concorrentes (cada um tipicamente uma chamada OpenRouter a um MODELO
diferente), com TETO de custo em dólar, coleta fail-soft e telemetria injetável.

PROVIDER-AGNÓSTICO de propósito: NÃO conhece OpenRouter no topo, NÃO sabe o que é o domínio
de quem chama. Recebe *jobs* — cada job é um thunk `() -> (valor, custo_usd)`.
Isso mantém o motor folha (importável por qualquer aplicação, zero acoplamento reverso; mesmo
invariante de openrouter.py) e é a costura de DIP: quem chama decide provider/modelo/telemetria.

SOLID:
- SRP: só faz dispatch paralelo + ledger de custo + telemetria. Nada de modelo/domínio/gate.
- DIP: depende de ABSTRAÇÕES (Job.run thunk; on_event callback) — não de OpenRouter nem de um
  emitter concreto. Adapters (make_openrouter_text_job) plugam por injeção.
- OCP: worker novo (visão, código, juiz) = job-builder novo, sem tocar no motor. Sink de
  telemetria novo = outro on_event.

Teto de custo em DUAS camadas: o teto DURO de verdade é a chave OpenRouter capada; ESTE é o
teto PRECISO best-effort. Antes de refilar um job, se o gasto acumulado já bateu o teto, os
jobs restantes são PULADOS (status "skipped_budget"). Como até `workers` jobs podem estar em
voo quando o teto é cruzado, o gasto pode ultrapassar em ~1 lote — por isso o cinto é a chave
capada e este é o suspensório.

Observabilidade: emite um dict estruturado por evento (squad_start, job_done, job_skipped,
squad_done) via on_event — modelo, custo, latência, gasto acumulado, status, erro. Quem chama
liga no sink que quiser (JSONL / cost-tracker / stdout). A telemetria é best-effort:
um sink que levanta NUNCA derruba a squad.
"""
from __future__ import annotations

import concurrent.futures
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


@dataclass
class Job:
    """Uma unidade de trabalho da squad.

    `run` é um thunk SEM efeitos colaterais compartilhados que devolve `(valor, custo_usd)`.
    O motor não interpreta `valor` (pode ser texto, dict, veredito...). `model` é só rótulo
    p/ telemetria/roteamento — o motor não o usa pra decidir nada."""
    key: str
    run: Callable[[], "tuple[Any, float]"]
    model: Optional[str] = None


@dataclass
class JobResult:
    key: str
    model: Optional[str]
    ok: bool
    value: Any
    cost_usd: float
    latency_ms: int
    error: Optional[str] = None
    status: str = "ok"  # ok | error | skipped_budget


@dataclass
class SquadReport:
    results: list  # list[JobResult]
    total_cost_usd: float
    n_ok: int
    n_error: int
    n_skipped: int
    budget_usd: Optional[float]
    budget_hit: bool


def _noop_event(_ev: dict) -> None:
    pass


def make_jsonl_sink(path: "str | Path") -> Callable[[dict], None]:
    """Sink de telemetria REAL p/ `on_event`: cada evento vira 1 linha JSONL (append-only, flush
    imediato — sobrevive a crash no meio de um lote longo). `run_squad._emit` já embrulha o
    sink em try/except (best-effort, nunca derruba a squad); este sink em si também nunca
    levanta pro chamador direto (best-effort self-contido, mesmo espírito). stdlib-only (json +
    pathlib), sem depender de emitter/cost-tracker do repo — quem quiser outro destino injeta o
    próprio `on_event` (OCP)."""
    p = Path(path)

    def _sink(event: dict) -> None:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**event, "ts": time.time()}, ensure_ascii=False) + "\n")
                fh.flush()
        except Exception:  # noqa: BLE001 — telemetria nunca derruba o fluxo (mesmo contrato do on_event)
            pass

    return _sink


def run_squad(
    jobs: Iterable[Job],
    *,
    workers: int = 4,
    budget_usd: Optional[float] = None,
    on_event: Optional[Callable[[dict], None]] = None,
) -> SquadReport:
    """Roda os jobs em paralelo (pool com limite `workers`), respeitando `budget_usd`.

    - fail-soft: um job que levanta vira JobResult(status="error"), não derruba a squad.
    - budget: quando o gasto acumulado >= budget_usd, os jobs ainda não despachados viram
      "skipped_budget". `None` = sem teto. `0` = teto zero (não despacha nada).
    - telemetria: on_event(dict) por etapa (best-effort; um sink que quebra é ignorado).
    """
    emit = on_event or _noop_event

    def _emit(ev: dict) -> None:
        try:
            emit(ev)
        except Exception:  # noqa: BLE001 — telemetria é best-effort, nunca derruba o fluxo
            pass

    workers = max(1, int(workers))
    jobs_iter = iter(jobs)
    results: list = []
    spent = 0.0
    budget_hit = False

    def over_budget() -> bool:
        return budget_usd is not None and spent >= budget_usd

    def _exec(job: Job) -> JobResult:
        t0 = time.perf_counter()
        try:
            value, cost = job.run()
            return JobResult(job.key, job.model, True, value, float(cost or 0.0),
                             int((time.perf_counter() - t0) * 1000), None, "ok")
        except Exception as e:  # noqa: BLE001 — fail-soft é o ponto: um worker ruim não mata a frota
            return JobResult(job.key, job.model, False, None, 0.0,
                             int((time.perf_counter() - t0) * 1000),
                             f"{type(e).__name__}: {e}", "error")

    _emit({"event": "squad_start", "workers": workers, "budget_usd": budget_usd})

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        inflight: dict = {}

        def _fill() -> None:
            # Submete jobs até encher o pool OU bater o teto. Só LÊ spent/budget (closure).
            while len(inflight) < workers and not over_budget():
                job = next(jobs_iter, None)
                if job is None:
                    break
                inflight[ex.submit(_exec, job)] = job

        _fill()
        while inflight:
            done, _ = concurrent.futures.wait(
                inflight, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                inflight.pop(fut)
                res = fut.result()
                spent += res.cost_usd
                results.append(res)
                _emit({"event": "job_done", "key": res.key, "model": res.model,
                       "ok": res.ok, "status": res.status, "cost_usd": res.cost_usd,
                       "latency_ms": res.latency_ms, "spent_usd": round(spent, 6),
                       "error": res.error})
            if over_budget():
                budget_hit = True
            else:
                _fill()

    # Jobs não despachados (teto batido) -> pulados explicitamente (auditável).
    for job in jobs_iter:
        res = JobResult(job.key, job.model, False, None, 0.0, 0,
                        "skipped: budget cap reached", "skipped_budget")
        results.append(res)
        budget_hit = True
        _emit({"event": "job_skipped", "key": res.key, "model": res.model, "reason": "budget"})

    n_ok = sum(1 for r in results if r.status == "ok")
    n_error = sum(1 for r in results if r.status == "error")
    n_skipped = sum(1 for r in results if r.status == "skipped_budget")
    report = SquadReport(results, round(spent, 6), n_ok, n_error, n_skipped, budget_usd, budget_hit)
    _emit({"event": "squad_done", "total_cost_usd": report.total_cost_usd, "n_ok": n_ok,
           "n_error": n_error, "n_skipped": n_skipped, "budget_hit": budget_hit})
    return report


# ── Helpers de custo (puros, testáveis sem rede) ────────────────────────────

def cost_from_openrouter_usage(usage: Any, price_in_per_mtok: float, price_out_per_mtok: float) -> float:
    """Custo USD de uma resposta OpenRouter. Usa `usage.cost` explícito se vier; senão calcula
    por tokens × preço/Mtok. Robusto a `usage` ausente/estranho -> 0.0 (nunca levanta)."""
    if not isinstance(usage, dict):
        return 0.0
    c = usage.get("cost")
    if isinstance(c, (int, float)):
        return float(c)
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    return (prompt / 1_000_000.0) * price_in_per_mtok + (completion / 1_000_000.0) * price_out_per_mtok


def estimate_cost(n_calls: int, avg_in_tokens: float, avg_out_tokens: float,
                  price_in_per_mtok: float, price_out_per_mtok: float) -> float:
    """Estimativa PRÉ-VOO: custo total de n_calls a esse preço. Pra decidir se cabe no teto
    ANTES de disparar a squad (ou encolher o painel)."""
    per = ((avg_in_tokens / 1_000_000.0) * price_in_per_mtok
           + (avg_out_tokens / 1_000_000.0) * price_out_per_mtok)
    return round(n_calls * per, 6)


# ── Adapters de provider (ponte pro chokepoint; ponto de extensão OCP) ───────

def make_text_job(
    key: str,
    prompt: str,
    model: str,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    *,
    system: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    provider: Any = None,
) -> Job:
    """Monta um Job de TEXTO que chama `model` no `provider` e devolve `({model, text}, custo_usd)`.

    `provider` = um `providers.Provider` (`None` = OpenRouter, o default de sempre). É o único
    ponto do motor que sabe de provider — e mesmo assim só o REPASSA ao chokepoint, que resolve
    base_url/chave/headers. Rodar o mesmo roster em outro provider = passar outro `provider`.

    `max_tokens` (opcional) limita a saída — útil pra custo previsível E comparação JUSTA (todo
    modelo do painel com o mesmo teto de saída; um modelo verboso não distorce custo/veredito).

    Import LAZY de openrouter (mantém o motor sem dependência de import no topo e facilita o
    mock nos testes: monkeypatch em `super_squad.openrouter.openrouter_messages_raw`)."""
    def _run() -> "tuple[dict, float]":
        from .openrouter import openrouter_messages_raw
        data = openrouter_messages_raw(
            [{"role": "user", "content": prompt}],
            system=system, model=model, temperature=temperature, timeout=timeout,
            api_key=api_key, max_tokens=max_tokens, provider=provider,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            text = ""
        cost = cost_from_openrouter_usage(data.get("usage"), price_in_per_mtok, price_out_per_mtok)
        return {"model": model, "text": text}, cost

    return Job(key=key, run=_run, model=model)


def make_openrouter_text_job(
    key: str,
    prompt: str,
    model: str,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    *,
    system: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Job:
    """Job de texto no OPENROUTER (chave OPENROUTER_API_KEY, slugs `provider/modelo`).
    Nome/assinatura/comportamento de SEMPRE — é `make_text_job` com o provider default."""
    return make_text_job(
        key, prompt, model, price_in_per_mtok, price_out_per_mtok,
        system=system, temperature=temperature, timeout=timeout, api_key=api_key,
        max_tokens=max_tokens, provider=None,
    )


def make_qwen_text_job(
    key: str,
    prompt: str,
    model: str,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    *,
    system: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Job:
    """Peer de `make_openrouter_text_job` no QWEN CLOUD (Alibaba Cloud Model Studio / DashScope):
    mesma forma, mesmo custeio por `usage`, chave DASHSCOPE_API_KEY, slugs `qwen-plus`/`qwen-max`.
    Um roster inteiro roda no Qwen Cloud trocando só o factory (ver `qwen_cloud.py`).

    Import LAZY de providers (motor sem dependência de import no topo)."""
    from .providers import QWEN_CLOUD
    return make_text_job(
        key, prompt, model, price_in_per_mtok, price_out_per_mtok,
        system=system, temperature=temperature, timeout=timeout, api_key=api_key,
        max_tokens=max_tokens, provider=QWEN_CLOUD,
    )


def make_openrouter_vision_job(
    key: str,
    prompt: str,
    images: "list[str]",
    model: str,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    *,
    system: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: Optional[str] = None,
) -> Job:
    """Peer de make_openrouter_text_job pra visão: monta um Job que chama um modelo
    OpenRouter MULTIMODAL (`images` = URLs http(s) ou data-URIs) e devolve
    `({model, text}, custo_usd)`. Usa `openrouter_chat_vision_raw` (não `openrouter_chat_vision`)
    porque o motor precisa do `usage` cru pra custear — a variante texto-só descarta isso.

    Import LAZY (mesmo motivo do text job: motor sem dependência de import no topo; mock nos
    testes via monkeypatch em `super_squad.openrouter.openrouter_chat_vision_raw`)."""
    def _run() -> "tuple[dict, float]":
        from .openrouter import openrouter_chat_vision_raw
        data = openrouter_chat_vision_raw(
            prompt, images, system=system, model=model, temperature=temperature,
            timeout=timeout, api_key=api_key,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            text = ""
        cost = cost_from_openrouter_usage(data.get("usage"), price_in_per_mtok, price_out_per_mtok)
        return {"model": model, "text": text}, cost

    return Job(key=key, run=_run, model=model)


# ── Agregador de painel (voto majoritário/consenso) — puro, sem rede ────────

_VERDICT_SEVERITY: dict = {"GOOD": 0, "OK": 1, "BAD": 2}  # tie-break: mais conservador vence


def parse_verdict_keyword(
    raw: str, *, keywords: "tuple[str, ...]" = ("GOOD", "OK", "BAD"), default: str = "BAD",
) -> str:
    """Extrai a 1ª `keyword` por PALAVRA (word-boundary) e PRIMEIRA posição no texto — robusto a
    'BAD, not good' (= BAD, não GOOD) e a 'LOOKS' (não casa 'OK' dentro de outra palavra). Sem
    keyword encontrada -> `default` (conservador). Genérico/reusável — não é específico de VLM
    (qualquer painel de juízes texto-cru pode usar)."""
    import re

    u = (raw or "").upper()
    hits = [(m.start(), k) for k in keywords if (m := re.search(rf"\b{k}\b", u))]
    if not hits:
        return default
    hits.sort()
    return hits[0][1]


def aggregate_panel_verdicts(
    results: "list[JobResult]", *,
    keywords: "tuple[str, ...]" = ("GOOD", "OK", "BAD"), default: str = "BAD",
    weights: "Optional[dict[str, float]]" = None,
) -> dict:
    """Agrega N `JobResult` (tipicamente de um painel cross-lab de `make_openrouter_vision_job`)
    por VOTO MAJORITÁRIO. Só resultados `ok=True` com `value={"model","text"}` votam; erro/skip
    entram no `panel` com `verdict=None` mas NÃO contam pra `n_valid`. Empate -> vence o veredito
    mais CONSERVADOR (BAD > OK > GOOD) — fail-closed-friendly. `n_valid=0` (painel inteiro fora do
    ar) -> `verdict=default` com n_valid=0 (o consumidor deve tratar n_valid=0 como fail-closed).
    Puro/testável sem rede — o motor (`run_squad`) já fez as chamadas.

    `weights` (DIP, opcional): `{model: peso}`, default 1.0 pra modelo ausente do dict. Achado
    empírico (painel de juízes de visão): 2 votos de modelos CONFIRMADAMENTE cegos a um defeito
    real (testado N=5) venciam 1 voto correto por maioria simples 2-1. Peso 2.0 pro
    modelo mais confiável, combinado com o tie-break conservador acima, resolve isso SEM dar
    poder de veto unilateral: o modelo com peso 2 nunca é batido em disputa de mesma severidade
    (2 contra 2 empata, e o empate já favorece o mais conservador), mas se os outros DOIS
    concordarem de forma independente em algo MAIS conservador que o peso-2, esse consenso ainda
    vence (2 contra 2, tie-break favorece o mais cauteloso de qualquer lado) — nunca reduz cautela,
    só evita que 2 votos confirmadamente cegos anulem 1 voto confirmadamente correto."""
    panel: list = []
    counts: dict = {}
    n_valid = 0
    for r in results:
        if r.ok:
            text = (r.value or {}).get("text", "") if isinstance(r.value, dict) else ""
            v = parse_verdict_keyword(text, keywords=keywords, default=default)
            panel.append({"model": r.model, "verdict": v, "ok": True})
            w = (weights or {}).get(r.model, 1.0)
            counts[v] = counts.get(v, 0) + w
            n_valid += 1
        else:
            panel.append({"model": r.model, "verdict": None, "ok": False, "error": r.error})

    if n_valid == 0:
        return {"verdict": default, "n_valid": 0, "panel": panel, "consensus": 0.0}

    total_weight = sum(counts.values())  # soma dos pesos (== n_valid quando weights=None)
    top_count = max(counts.values())
    tied = [k for k, c in counts.items() if c == top_count]
    verdict = max(tied, key=lambda k: _VERDICT_SEVERITY.get(k, 0))
    return {"verdict": verdict, "n_valid": n_valid, "panel": panel,
            "consensus": round(top_count / total_weight, 4)}
