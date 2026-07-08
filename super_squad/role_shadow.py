"""role_shadow.py — motor GENÉRICO de shadow-audit por papel (o FISCAL do Super Squad).

O padrão: para cada papel do squad, comparar uma régua DETERMINÍSTICA (grátis) contra o
AGENTE (pago) nos mesmos itens — e, quando existe, contra o GOLD humano — appendando cada
comparação num checkpoint JSONL incremental/idempotente (schema `role_shadow_audit/1`).
A discordância vai para revisão humana; a revisão corrige régua, prompt ou roster. Num dos
papéis de origem esse loop subiu a concordância de 61.76% para 80.39%.

Um `RoleAuditSpec` declara de onde vêm os itens, qual é a régua determinística, como
construir o agente e — quando existe — onde estão os golds humanos. O motor é agnóstico
ao domínio: papéis são registrados via `register_role` (OCP, mesmo padrão do maestro).

C9 (re-validação periódica) vira SUBPRODUTO: re-rodar com `key_suffix` (ex. `::2026-08`)
appenda uma rodada nova sem quebrar o dedup — o drift entre épocas aparece na comparação.

INVARIANTES (integridade do ground-truth): NUNCA decide nada, NUNCA escreve em gold/roster —
só compara e registra. Gold é lido, jamais escrito. Mudança de roster/peso = decisão HUMANA
informada pelo relatório. Fail-soft na leitura (item ruim não derruba a rodada); fail-fast
na construção (roster vazio levanta, igual aos factories).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SCHEMA = "role_shadow_audit/1"
# Checkpoints são do USUÁRIO (dados de execução, não do repo — ver .gitignore).
CHECKPOINT_DIR = Path(os.environ.get("SQUAD_CHECKPOINT_DIR", "_checkpoints"))


@dataclass(frozen=True)
class RoleAuditSpec:
    """Contrato de um papel auditável. `items_fn` -> [{"key": str, ...payload}] em ordem
    determinística; `deterministic_fn(item)` -> {"label": str|None, "abstain": bool, ...} (GRÁTIS,
    pode levantar — o motor fail-softa); `make_agent_fn(budget_usd)` -> agent(item) -> {"label",
    "cost_usd", ...} | None (PAGO; None = sem resposta por teto/painel cego); `gold_fn()` ->
    {key: label} (mão humana, SÓ leitura) ou None quando o papel não tem gold."""
    role: str
    items_fn: Callable[[], "list[dict]"]
    deterministic_fn: Callable[[dict], dict]
    make_agent_fn: Callable[[float], Callable]
    gold_fn: "Optional[Callable[[], dict]]" = None


ROLE_SPECS: "dict[str, Callable[[], RoleAuditSpec]]" = {}


def register_role(key: str, spec_factory: "Callable[[], RoleAuditSpec]") -> None:
    """Registra um papel auditável (OCP: papel novo = 1 factory registrada, motor intocado)."""
    if key in ROLE_SPECS:
        raise ValueError(f"papel duplicado: {key!r}")
    ROLE_SPECS[key] = spec_factory


def checkpoint_path_for(role: str) -> Path:
    return CHECKPOINT_DIR / f"role_shadow_{role}.jsonl"


def already_checkpointed(path: Path) -> "set[str]":
    """Chaves já gravadas num checkpoint JSONL (dedup do re-run)."""
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            keys.add(json.loads(line)["key"])
    return keys


def append_checkpoint_line(path: Path, entry: dict) -> None:
    """Append-only (sobrevive a crash); idempotência é responsabilidade do CHAMADOR (checar
    `already_checkpointed` antes) — este helper não dedup, só grava (adiciona `ts`)."""
    entry = dict(entry, ts=time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()


def run_role_audit(
    spec: RoleAuditSpec, checkpoint_path: Path, budget_usd: float, *,
    limit: "Optional[int]" = None, event_sink=None, key_suffix: str = "",
    legacy_checkpoints: "tuple[Path, ...]" = (),
) -> dict:
    """Roda a auditoria de UM papel: para cada item ainda não checkpointado, compara régua
    determinística vs agente e appenda 1 linha `role_shadow_audit/1`. Idempotente (dedup por
    `key+key_suffix`, incluindo `legacy_checkpoints` — nunca re-paga item já comparado por um
    script legado). Devolve o resumo com `spent_usd` (o maestro registra no ledger)."""
    done = set(already_checkpointed(checkpoint_path))
    for legacy in legacy_checkpoints:
        done |= already_checkpointed(Path(legacy))
    golds = dict(spec.gold_fn()) if spec.gold_fn is not None else {}
    agent = spec.make_agent_fn(budget_usd)

    def _emit(ev: dict) -> None:
        if event_sink is None:
            return
        try:
            event_sink(ev)
        except Exception:  # noqa: BLE001 — telemetria nunca derruba a rodada
            pass

    n_new = n_agree = n_disagree = n_error = n_no_answer = 0
    n_gold = n_det_correct = 0
    n_gold_agent = n_agent_correct = 0  # denominador PRÓPRIO do agente (papel SEM régua não
    spent = 0.0                         # pode zerar o denominador do agente)

    for item in spec.items_fn():
        key = str(item.get("key", ""))
        if not key:
            continue
        ck = key + key_suffix
        if ck in done:
            continue
        if limit is not None and n_new >= limit:
            break

        try:
            det = spec.deterministic_fn(item)
        except Exception as exc:  # noqa: BLE001 — régua quebrada num item não derruba a rodada
            det = {"label": None, "abstain": True, "error": repr(exc)}

        ag = None
        ag_error = None
        try:
            ag = agent(item)
        except Exception as exc:  # noqa: BLE001 — agente fora do ar/teto: registra e segue
            ag_error = repr(exc)

        det_label = det.get("label")
        ag_label = (ag or {}).get("label")
        if ag_error is not None:
            n_error += 1
            agree = None
        elif ag is None:
            n_no_answer += 1
            agree = None
        elif det_label is None or det.get("abstain") or ag_label is None:
            agree = None
        else:
            agree = bool(det_label == ag_label)
            if agree:
                n_agree += 1
            else:
                n_disagree += 1

        gold = golds.get(key)
        det_correct = (det_label == gold) if (gold is not None and det_label is not None) else None
        agent_correct = (ag_label == gold) if (gold is not None and ag_label is not None) else None
        if gold is not None and det_correct is not None:
            n_gold += 1
            if det_correct:
                n_det_correct += 1
        if gold is not None and agent_correct is not None:
            n_gold_agent += 1
            if agent_correct:
                n_agent_correct += 1

        cost = float((ag or {}).get("cost_usd") or 0.0)
        spent += cost

        # agent: dict com a resposta; {"error": ...} quando LEVANTOU; null quando sem-resposta
        # limpa (teto/painel cego) — sem-resposta NÃO é erro, os contadores distinguem os dois.
        row = {"schema": SCHEMA, "role": spec.role, "key": ck,
               "deterministic": det,
               "agent": ({"error": ag_error} if ag_error is not None else ag),
               "agree": agree, "gold": gold,
               "det_correct": det_correct, "agent_correct": agent_correct,
               "cost_usd": round(cost, 6)}
        append_checkpoint_line(checkpoint_path, row)  # adiciona ts
        done.add(ck)
        n_new += 1
        _emit({"event": "role_shadow_compared", "role": spec.role, "key": ck,
               "agree": agree, "cost_usd": cost})

    n_compared = n_agree + n_disagree
    return {
        "role": spec.role, "n_new": n_new, "n_agree": n_agree, "n_disagree": n_disagree,
        "n_error": n_error, "n_no_answer": n_no_answer,
        "agreement_rate": round(n_agree / n_compared, 4) if n_compared else None,
        "n_gold": n_gold,
        "n_gold_agent": n_gold_agent,
        "det_gold_acc": round(n_det_correct / n_gold, 4) if n_gold else None,
        "agent_gold_acc": round(n_agent_correct / n_gold_agent, 4) if n_gold_agent else None,
        "spent_usd": round(spent, 6),
        "checkpoint": str(checkpoint_path),
    }


def make_shadow_runner(role_key: str) -> "Callable[..., dict]":
    """Bridge p/ o maestro: `register(WorkflowSpec(name=f"shadow_{papel}", ...,
    runner=make_shadow_runner(papel)))`. Resolve o spec em ROLE_SPECS na hora de RODAR
    (lazy — registrar o workflow não constrói o agente) e liga o event_sink default num
    JSONL ao lado do checkpoint."""
    def runner(*, budget_usd: float, limit: "int | None" = None, event_sink=None,
               rerun_tag: str = "") -> dict:
        spec = ROLE_SPECS[role_key]()
        checkpoint = checkpoint_path_for(spec.role)
        if event_sink is None:
            from .squad import make_jsonl_sink  # noqa: E402 (lazy)
            event_sink = make_jsonl_sink(checkpoint.with_name(checkpoint.stem + "_events.jsonl"))
        return run_role_audit(spec, checkpoint, budget_usd, limit=limit,
                              event_sink=event_sink, key_suffix=rerun_tag)
    return runner
