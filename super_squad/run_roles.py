"""run_roles.py — PORTA PARALELA: vários subagents (papéis) trabalhando ao MESMO tempo.

`run_role` roda UM papel. Este roda N papéis (cada um com sua persona + roster medido) num ÚNICO
fan-out concorrente do `run_squad` — todos os jobs de todos os papéis disputam os mesmos workers e
o mesmo teto de gasto. É o que permite "colocar vários subagentes para trabalharem em paralelo":

    run_roles([
        {"role": "code-reviewer",    "input": diff},
        {"role": "security-auditor", "input": diff},
        {"role": "competitive-analyst", "input": brief},
    ])

CONSULTIVO (como `run_role`): injeta o system prompt da persona, lê TEXTO, nenhuma tool executa.
FAIL-SOFT por tarefa: um papel com roster VAZIO (ou persona ausente) vira um resultado de ERRO
naquela tarefa — NÃO derruba o lote (o motor já é fail-soft; aqui estendemos ao roteamento).
SOLID/DIP: `run_squad`/`make_job`/`load_role`/`roster` injetáveis → teste hermético sem rede.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence


def _normalize(task) -> dict:
    """Aceita `{"role","input",...}` ou a tupla `(role, input)` → dict canônico."""
    if isinstance(task, dict):
        return task
    role, task_input = task
    return {"role": role, "input": task_input}


def run_roles(
    tasks: Sequence,
    *,
    roles_dir: "str | Path" = "roles/vendor",
    skills_dir: "str | Path" = "roles/skills",
    api_key: "Optional[str]" = None,
    budget_usd: float = 0.50,
    temperature: float = 0.2,
    max_tokens: "Optional[int]" = None,
    timeout: int = 120,
    workers: "Optional[int]" = None,
    run_squad_fn: "Optional[Callable]" = None,
    make_job_fn: "Optional[Callable]" = None,
    load_role_fn: "Optional[Callable]" = None,
    roster_fn: "Optional[Callable]" = None,
    load_skill_fn: "Optional[Callable]" = None,
    compose_fn: "Optional[Callable]" = None,
) -> dict:
    """Roda cada tarefa `{role, input, panel?, label?, instruction?, skill?}` em PARALELO (titular do
    papel por default; `panel=True` roda todo o roster). Um só `run_squad` cobre todos os jobs.
    `instruction` (opt-in) prefixa uma diretiva-tarefa ao input (achado do smoke 07-12). `skill` (opt-in,
    D10) = nome de uma skill em `skills_dir` cujo playbook é COMPOSTO ao system prompt da persona
    (`compose_system`) — o gate D10 vale: skill que executa código (Fase 2) faz a tarefa ERRAR (fail-soft),
    não roda por fé.

    Devolve `{tasks:[{role, label, persona, skill, results:[...], error}], spent_usd}`. Tarefa com roster
    vazio/persona ausente/skill-gated → `error` preenchido, SEM abortar as outras."""
    if load_role_fn is None:
        from .roles import load_role as load_role_fn
    if roster_fn is None:
        from .registry import squad_roster as roster_fn
    if run_squad_fn is None:
        from .squad import run_squad as run_squad_fn
    if make_job_fn is None:
        from .squad import make_openrouter_text_job as make_job_fn
    if load_skill_fn is None:
        from .skills import load_skill as load_skill_fn
    if compose_fn is None:
        from .skills import compose_system as compose_fn

    norm = [_normalize(t) for t in tasks]
    jobs = []
    plan: list = []  # espelha `norm`: {role, label, persona, keys[], error}
    for i, t in enumerate(norm):
        role = t["role"]
        label = t.get("label", role)
        entry = {"role": role, "label": label, "persona": None, "skill": t.get("skill"),
                 "keys": [], "error": None}
        try:
            spec = load_role_fn(Path(roles_dir) / f"{role}.md")
            entry["persona"] = spec.name
            # skill opt-in (D10): compõe o playbook ao system prompt. O gate (SkillGateError p/ skill que
            # executa código) sobe aqui dentro do try → vira erro DA TAREFA, não roda por fé.
            system = spec.system_prompt
            if t.get("skill"):
                skill = load_skill_fn(Path(skills_dir) / f"{t['skill']}.md")
                system = compose_fn(system, skill)
            roster = list(roster_fn(role))
            if not roster:
                raise RuntimeError(
                    f"roster VAZIO — defina env AI_SQUAD_ROSTER_{role.upper().replace('-', '_')}"
                )
            if not t.get("panel"):
                roster = roster[:1]
            # instruction opt-in: prefixa uma diretiva-tarefa clara ao input. Personas VERBOSAS de
            # catálogo ("query context manager first") emitem ruído de protocolo sem isso — o smoke
            # 07-12 pegou; uma instrução explícita (como o gold de medição faz) suprime o desvio.
            body = f"{t['instruction'].strip()}\n\n{t['input']}" if t.get("instruction") else t["input"]
            for slug, pin, pout in roster:
                key = f"{i}::{role}::{slug}"
                entry["keys"].append(key)
                jobs.append(make_job_fn(key, body, slug, pin, pout,
                                        system=system, temperature=temperature,
                                        timeout=timeout, api_key=api_key, max_tokens=max_tokens))
        except Exception as exc:  # noqa: BLE001 — papel quebrado vira erro DA TAREFA, não do lote
            entry["error"] = str(exc)
        plan.append(entry)

    n_workers = workers if workers is not None else max(1, len(jobs))
    report = run_squad_fn(jobs, workers=n_workers, budget_usd=budget_usd) if jobs else None
    by_key = {r.key: r for r in (report.results if report else [])}

    out_tasks = []
    for entry in plan:
        results = []
        for key in entry["keys"]:
            r = by_key.get(key)
            if r is None:
                results.append({"model": key.split("::")[-1], "ok": False,
                                "cost_usd": 0.0, "text": None, "error": "sem resultado (teto?)"})
            else:
                results.append({
                    "model": r.model, "ok": r.ok, "cost_usd": r.cost_usd,
                    "text": ((r.value or {}).get("text", "") if r.ok and isinstance(r.value, dict) else None),
                    "error": r.error,
                })
        out_tasks.append({"role": entry["role"], "label": entry["label"],
                          "persona": entry["persona"], "skill": entry["skill"],
                          "results": results, "error": entry["error"]})

    return {"tasks": out_tasks,
            "spent_usd": report.total_cost_usd if report else 0.0}


def main(argv=None) -> int:
    """CLI: `python -m super_squad.run_roles tasks.json [--budget 0.5] [--panel]`.
    `tasks.json` = `[{"role":"code-reviewer","input":"..."}, ...]` (ou lista de pares [role, input]).
    Lê OPENROUTER_API_KEY e os rosters (env AI_SQUAD_ROSTER_<PAPEL>) do ambiente."""
    import argparse
    import json
    import os
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(description="Roda vários subagents (papéis) em paralelo.")
    ap.add_argument("tasks_json", help="arquivo JSON com a lista de tarefas {role,input,panel?}")
    ap.add_argument("--roles-dir", default="roles/vendor")
    ap.add_argument("--budget", type=float, default=0.50)
    ap.add_argument("--panel", action="store_true", help="cada papel roda todo o roster")
    ap.add_argument("--max-tokens", type=int, default=None)
    a = ap.parse_args(argv)

    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERRO: OPENROUTER_API_KEY ausente no env.", file=sys.stderr)
        return 2
    tasks = json.loads(Path(a.tasks_json).read_text(encoding="utf-8"))
    if a.panel:
        for t in tasks:
            if isinstance(t, dict):
                t.setdefault("panel", True)
    out = run_roles(tasks, roles_dir=a.roles_dir, budget_usd=a.budget, max_tokens=a.max_tokens)
    for t in out["tasks"]:
        if t["error"]:
            print(f"=== {t['label']} :: ERRO: {t['error']}\n")
            continue
        for r in t["results"]:
            print(f"=== {t['label']} @ {r['model']} ===")
            print(r["text"] if r["ok"] else f"(falhou: {r['error']})")
            print()
    print(f"[spent ${out['spent_usd']:.6f}  tasks={len(out['tasks'])}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
