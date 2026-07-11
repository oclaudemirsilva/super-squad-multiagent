"""run_role.py — a PORTA DA FRENTE: rode um subagent (persona) sobre um input, com uma chamada.

Carrega a persona, escolhe o(s) modelo(s) rosteado(s) (roster PRIVADO via registry/override env),
roda pelo motor e devolve o veredito. É o que permite OUTRO projeto/sessão usar um subagent
MEDIDO sem conhecer as tripas: `run_role("code-reviewer", diff)` → texto do veredito.

CONSULTIVO por design: injeta o system prompt da persona e lê a resposta em TEXTO — nenhuma tool
executa (uma persona-construtora roda como CONSELHEIRA aqui; construir de verdade é Fase 2). Isso
mantém o reuso seguro (zero disco/bash) e cobre todo papel de ler-e-julgar.

SOLID/DIP: `run_squad`/`make_job`/`load_role`/`roster` são injetáveis → teste hermético sem rede.
O roster é a parte PRIVADA (D1): sem override `AI_SQUAD_ROSTER_<PAPEL>` o papel não tem modelo e
`run_role` falha rápido com a mensagem certa (nunca roda com agent silencioso — D4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional


def run_role(
    role: str,
    task_input: str,
    *,
    roles_dir: "str | Path" = "roles/vendor",
    roster: "Optional[list]" = None,
    api_key: "Optional[str]" = None,
    budget_usd: float = 0.10,
    temperature: float = 0.2,
    max_tokens: "Optional[int]" = None,
    timeout: int = 120,
    panel: bool = False,
    run_squad_fn: "Optional[Callable]" = None,
    make_job_fn: "Optional[Callable]" = None,
    load_role_fn: "Optional[Callable]" = None,
    roster_fn: "Optional[Callable]" = None,
) -> dict:
    """Roda o papel `role` sobre `task_input`. Por default usa o TITULAR do roster (1ª linha);
    `panel=True` roda todas as linhas do roster e devolve todos os vereditos.

    Devolve `{role, persona, results:[{model,text,ok,cost_usd,error}], spent_usd}` (+ `model`/`text`
    do titular quando `panel=False`). Levanta RuntimeError se o roster do papel estiver vazio."""
    if load_role_fn is None:
        from .roles import load_role as load_role_fn
    if roster_fn is None:
        from .registry import squad_roster as roster_fn
    if run_squad_fn is None:
        from .squad import run_squad as run_squad_fn
    if make_job_fn is None:
        from .squad import make_openrouter_text_job as make_job_fn

    spec = load_role_fn(Path(roles_dir) / f"{role}.md")
    entries = list(roster if roster is not None else roster_fn(role))
    if not entries:
        raise RuntimeError(
            f"papel {role!r} com roster VAZIO — meça e preencha o modelo via env "
            f"AI_SQUAD_ROSTER_{role.upper().replace('-', '_')} = 'slug:pin:pout,...' "
            f"(o roster é o edge PRIVADO — ver registry.py / D1). Sem modelo, o papel não roda."
        )
    if not panel:
        entries = entries[:1]

    jobs = [
        make_job_fn(f"{role}::{slug}", task_input, slug, pin, pout,
                    system=spec.system_prompt, temperature=temperature,
                    timeout=timeout, api_key=api_key, max_tokens=max_tokens)
        for slug, pin, pout in entries
    ]
    report = run_squad_fn(jobs, workers=max(1, len(jobs)), budget_usd=budget_usd)
    results = [
        {"model": r.model, "ok": r.ok, "cost_usd": r.cost_usd,
         "text": ((r.value or {}).get("text", "") if r.ok and isinstance(r.value, dict) else None),
         "error": r.error}
        for r in report.results
    ]
    out = {"role": role, "persona": spec.name, "results": results,
           "spent_usd": report.total_cost_usd}
    if not panel:
        out["model"] = results[0]["model"] if results else None
        out["text"] = results[0]["text"] if results else None
    return out


def main(argv=None) -> int:
    """CLI: `python -m super_squad.run_role <papel> "<input>" [--panel] [--budget 0.1]`.
    Lê OPENROUTER_API_KEY e o roster (env AI_SQUAD_ROSTER_<PAPEL>) do ambiente."""
    import argparse
    import os
    import sys

    # saída de modelo traz unicode (emoji, aspas curvas); stdout do Windows é cp1252 -> reconfigura
    # p/ utf-8 tolerante, senão o print do veredito quebra com UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — stream sem reconfigure (ex.: redirecionado) segue em frente
            pass

    ap = argparse.ArgumentParser(description="Roda um subagent (persona + roster) sobre um input.")
    ap.add_argument("role", help="papel, ex.: code-reviewer (usa roles/vendor/<papel>.md)")
    ap.add_argument("input", help="o texto/código a submeter ao papel")
    ap.add_argument("--roles-dir", default="roles/vendor")
    ap.add_argument("--budget", type=float, default=0.10)
    ap.add_argument("--panel", action="store_true", help="roda todo o roster, não só o titular")
    ap.add_argument("--max-tokens", type=int, default=None)
    a = ap.parse_args(argv)

    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERRO: OPENROUTER_API_KEY ausente no env.", file=sys.stderr)
        return 2
    try:
        out = run_role(a.role, a.input, roles_dir=a.roles_dir, budget_usd=a.budget,
                       max_tokens=a.max_tokens, panel=a.panel)
    except Exception as exc:  # noqa: BLE001 — CLI: mensagem limpa, não stacktrace
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    for r in out["results"]:
        head = f"=== {out['role']} @ {r['model']} ==="
        print(head)
        print(r["text"] if r["ok"] else f"(falhou: {r['error']})")
        print()
    print(f"[spent ${out['spent_usd']:.6f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
