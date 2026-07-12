"""gold_preflight.py — pré-voo do GOLD (guarda D6-anti-erro-de-autor): veta CASO-LIMPO antes de gastar.

MODO DE FALHA RECORRENTE que este módulo mata: o autor humano marca um trecho como "limpo"
(sem bug), mas ele TEM um problema legítimo e sutil (ex.: `os.path.basename` sozinho não impede
escape via SYMLINK; `for...of await` sequencial tem custo de performance). Aí a régua de over-flag
conta a minúcia CORRETA do modelo como "alucinação", e a medição inteira sai enviesada — descoberto
só lendo os outputs à mão, por sorte, DEPOIS de queimar orçamento. Aconteceu ≥2× na linhagem.

CONSERTO SISTÊMICO: antes de usar um caso-limpo como âncora de scoring, rode a persona por um JUIZ
MEDIDO (default = o titular do papel; barato e paridade-frontier) N vezes. Um caso genuinamente limpo
elicia `TOP_BUG: NONE` de forma consistente. Se a taxa de sinalização passa do limiar, o caso é
SUSPEITO — o gate REPROVA (fail-closed) e devolve os MOTIVOS citados pra revisão humana.

INTEGRIDADE (D6 preservado): o modelo NÃO autora nem remove o caso — ele só SINALIZA candidatos pra
banca humana. A decisão de consertar/remover é do humano. Modelo aconselha, humano decide — sem
autofagia (o gold nunca é escrito por modelo).

SOLID/DIP: `batch_run_fn` é INJETADO (default = build de jobs OpenRouter + `run_squad`), então os
testes rodam 100% herméticos (reviews canônicas, zero rede).

RÉGUA — ponto FINO (a lição de por que a v1 deste gate errou): o gate ESPELHA a régua de scoring,
`top_bug_forbids_ruler(forbid_any)` — sinaliza SÓ quando o juiz nomeia a vuln PROIBIDA específica
(a que o autor jurou ausente). NÃO usa `top_bug_clean_ruler` (qualquer-preocupação): um caso limpo
de verdade AINDA elicia preocupações defensáveis DIFERENTES ("SELECT * é desperdício", "sem validação
de entrada") que NÃO são over-flag — puni-las geraria suspeito FALSO e mataria a confiança no gate.
Assim o gate pré-computa exatamente o over-flag que o scoring produziria, com o juiz medido, ANTES
de gastar no pool inteiro. Sem `forbid_any` no caso -> cai pro `top_bug_clean_ruler` (melhor esforço).
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from .rulers import top_bug_clean_ruler, top_bug_forbids_ruler

# Suspeito por default se ≥40% das amostras sinalizam algo: separa CONSENSO (bug real: basename ~0.6-0.8)
# de RUÍDO ocasional (caso limpo de verdade ~0.0-0.2). Fail-closed: o humano libera o que for ruído.
_DEFAULT_SUSPECT_THRESHOLD = 0.40


class GoldPreflightError(RuntimeError):
    """Pré-voo do gold REPROVOU: ao menos um caso-limpo é suspeito de NÃO ser limpo (bloqueante)."""


def _build_prompt(instruction: str, language: str, diff: str) -> str:
    """Mesmo molde do runner de code-review: instrução + bloco cercado com a linguagem."""
    return f"{instruction}\n\n```{language}\n{diff}\n```"


def _default_batch_run_fn(
    specs: "list[tuple[str, str, str, str]]",
    *,
    api_key: Optional[str],
    temperature: float,
    timeout: int,
    max_tokens: Optional[int],
    workers: int,
    budget_usd: float,
) -> "dict[str, str]":
    """Default REAL: cada spec (key, system, prompt, model) vira um job OpenRouter e roda no
    `run_squad` (dogfood do motor). Devolve {key: texto}. Import tardio p/ não puxar rede quando
    injetado nos testes. Preço 0/0 aqui: este pré-voo não faz contabilidade de roster, só gasta pouco."""
    from .squad import run_squad, make_openrouter_text_job

    jobs = [
        make_openrouter_text_job(
            key, prompt, model, 0.0, 0.0,
            system=system, temperature=temperature, timeout=timeout,
            api_key=api_key, max_tokens=max_tokens,
        )
        for (key, system, prompt, model) in specs
    ]
    report = run_squad(jobs, workers=workers, budget_usd=budget_usd)
    return {r.key: r.value["text"] for r in report.results if r.ok}


def clean_case_flag_rates(
    cases: dict,
    system_prompt: str,
    judge_pool: "Sequence[str]",
    *,
    n: int = 5,
    api_key: Optional[str] = None,
    temperature: float = 0.4,
    timeout: int = 120,
    max_tokens: Optional[int] = 800,
    workers: int = 5,
    budget_usd: float = 0.50,
    batch_run_fn: Optional[Callable] = None,
) -> dict:
    """Roda cada CASO-LIMPO de `cases` por cada juiz de `judge_pool`, N vezes, e mede a taxa de
    SINALIZAÇÃO (fração de amostras cujo `TOP_BUG` NÃO declara ausência de bug). Um caso limpo de
    verdade tem taxa baixa; taxa alta = o juiz enxerga um problema real → suspeito.

    DIP: `batch_run_fn(specs, **kw) -> {key: texto}` injetável (default = OpenRouter+run_squad).
    Retorna `{case_id: {flag_rate, n_samples, reasons[]}}` — `reasons` = as linhas TOP_BUG que
    sinalizaram (o PORQUÊ, pra banca humana)."""
    run = batch_run_fn or _default_batch_run_fn
    instruction = cases["instruction"]
    clean_cases = [c for c in cases["cases"] if c["kind"] == "clean"]

    specs: list = []
    for case in clean_cases:
        prompt = _build_prompt(instruction, case["language"], case["diff"])
        for model in judge_pool:
            for rep in range(n):
                key = f"{case['id']}::{model}::{rep}"
                specs.append((key, system_prompt, prompt, model))

    texts = run(
        specs, api_key=api_key, temperature=temperature, timeout=timeout,
        max_tokens=max_tokens, workers=workers, budget_usd=budget_usd,
    )

    # régua POR-CASO: espelha o scoring — `forbids(forbid_any)` (nomeou a vuln proibida?);
    # sem forbid_any -> `clean` genérico (melhor esforço). Ver docstring (a lição do gate v1).
    ruler_by_case = {
        c["id"]: (top_bug_forbids_ruler(c["forbid_any"]) if c.get("forbid_any")
                  else top_bug_clean_ruler())
        for c in clean_cases
    }
    agg: dict = {c["id"]: {"flagged": 0, "n_samples": 0, "reasons": []} for c in clean_cases}
    for key, text in texts.items():
        case_id = key.split("::")[0]
        if case_id not in agg:
            continue
        verdict = ruler_by_case[case_id](text)
        agg[case_id]["n_samples"] += 1
        if not verdict["pass"]:  # sinalizou a vuln proibida (ou, sem forbid, qualquer bug)
            agg[case_id]["flagged"] += 1
            reason = verdict.get("detail", {}).get("top_bug")
            if reason:
                agg[case_id]["reasons"].append(reason)

    out: dict = {}
    for cid, d in agg.items():
        ns = d["n_samples"]
        out[cid] = {
            "flag_rate": (d["flagged"] / ns) if ns else None,
            "n_samples": ns,
            "reasons": d["reasons"][:6],  # amostra dos motivos, não a lista inteira
        }
    return out


def validate_clean_cases(
    cases: dict,
    system_prompt: str,
    judge_pool: "Sequence[str]",
    *,
    suspect_threshold: float = _DEFAULT_SUSPECT_THRESHOLD,
    **kw,
) -> dict:
    """Roda `clean_case_flag_rates` e classifica cada caso-limpo como OK ou SUSPEITO (taxa de
    sinalização ≥ `suspect_threshold`, OU nenhuma amostra = inconclusivo → suspeito, fail-closed).
    NÃO levanta — devolve `{ok, suspects[], rates{}}`. Use `assert_clean_cases_valid` p/ bloquear."""
    rates = clean_case_flag_rates(cases, system_prompt, judge_pool, **kw)
    suspects = []
    for cid, r in rates.items():
        fr = r["flag_rate"]
        if fr is None or fr >= suspect_threshold:
            suspects.append({
                "case_id": cid,
                "flag_rate": fr,
                "n_samples": r["n_samples"],
                "reasons": r["reasons"],
            })
    return {"ok": not suspects, "suspects": suspects, "rates": rates}


def assert_clean_cases_valid(
    cases: dict,
    system_prompt: str,
    judge_pool: "Sequence[str]",
    *,
    suspect_threshold: float = _DEFAULT_SUSPECT_THRESHOLD,
    **kw,
) -> dict:
    """Roda a validação e LEVANTA `GoldPreflightError` se algum caso-limpo for suspeito de não ser
    limpo (bloqueante — não meça over-flag contra um caso que talvez tenha bug real). Devolve o
    relatório em caso de sucesso. Preserva D6: o erro pede REVISÃO HUMANA, não conserta sozinho."""
    report = validate_clean_cases(cases, system_prompt, judge_pool,
                                  suspect_threshold=suspect_threshold, **kw)
    if not report["ok"]:
        lines = []
        for s in report["suspects"]:
            fr = "n/a" if s["flag_rate"] is None else f"{s['flag_rate']:.0%}"
            reason = s["reasons"][0] if s["reasons"] else "(sem amostra / sem motivo)"
            lines.append(f"  - {s['case_id']}: sinalizado {fr} — ex.: {reason[:120]}")
        raise GoldPreflightError(
            "pré-voo do GOLD REPROVOU: "
            f"{len(report['suspects'])} caso(s)-limpo(s) suspeito(s) de NÃO ser(em) limpo(s) "
            "(o juiz medido enxerga problema real). REVISÃO HUMANA antes de usar como âncora de "
            "over-flag — conserte o trecho ou remova o caso:\n" + "\n".join(lines)
        )
    return report
