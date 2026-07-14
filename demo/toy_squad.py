"""Demo toy end-to-end do loop de fiscalização — papel "sentiment_judge" (POS/NEG).

O que a demo mostra, sem nenhum dado proprietário:
1. Uma régua DETERMINÍSTICA grátis (léxico naive, fraca DE PROPÓSITO) roda em todo item.
2. O AGENTE pago (painel de modelos via OpenRouter) roda nos MESMOS itens.
3. O GOLD humano hardcoded mede os dois; o checkpoint JSONL registra cada comparação.
A discordância régua×agente×gold é o produto: é ela que vai pra revisão humana.

Dry-run por default — sem `--execute` nada gasta:
    python -m demo.toy_squad --list
    python -m demo.toy_squad shadow_sentiment_judge                      # só o plano
    python -m demo.toy_squad shadow_sentiment_judge --execute --limit 6  # gasta ~$0.001

Guardas em ação (features, não bugs — rode para VER):
- SEM a chave do provider ativo (OPENROUTER_API_KEY, ou DASHSCOPE_API_KEY no Qwen Cloud),
  `--execute` ABORTA no pré-voo com mensagem clara (nada de rodada silenciosa com agent=null):
  python -m demo.toy_squad shadow_sentiment_judge --execute
- SEM roster, o runner falha com instrução de configuração. Roster por env (o registry
  nasce vazio de propósito — meça os SEUS modelos antes de confiar neles):
  AI_SQUAD_ROSTER_SENTIMENT_JUDGE="google/gemini-2.5-flash:0.30:2.50,deepseek/deepseek-chat:0.27:1.10"

PROVIDER: a demo roda no provider ATIVO (env `AI_SQUAD_PROVIDER`; default `openrouter`). Pra
rodar o painel INTEIRO no Qwen Cloud (Alibaba Cloud Model Studio / DashScope — ver
`super_squad/qwen_cloud.py`), basta trocar env, sem tocar código:
    AI_SQUAD_PROVIDER=qwen_cloud DASHSCOPE_API_KEY=... \
    AI_SQUAD_ROSTER_SENTIMENT_JUDGE="qwen-plus:0.4:1.2,qwen-max:1.6:6.4" \
    python -m demo.toy_squad shadow_sentiment_judge --execute --limit 6
(preços do roster = USD/Mtok do catálogo do provider; slugs do Qwen Cloud são `qwen-*`, sem `/`.)
"""
from typing import Optional

from super_squad.role_shadow import RoleAuditSpec, register_role, make_shadow_runner
from super_squad.maestro import WorkflowSpec, register, main as maestro_main
from super_squad.providers import default_provider
from super_squad.registry import squad_roster
from super_squad.squad import run_squad, make_text_job, aggregate_panel_verdicts

# ── GOLD humano (hardcoded; num projeto real: arquivo de mão humana, SÓ leitura) ──────────
# Duas armadilhas calibradas p/ a régua naive ERRAR (não só abster) — é o desacordo didático:
#   "Not good at all"  -> a régua ignora negação => vê "good" e diz POS (gold: NEG)
#   "Never disappoints" -> a régua trata "never" como negativo cego a contexto => NEG (gold: POS)
GOLD_ITEMS = [
    ("I love this product", "POS"),
    ("This is awful", "NEG"),
    ("Not good at all", "NEG"),
    ("Never disappoints", "POS"),
    ("Great service", "POS"),
    ("Terrible experience", "NEG"),
    ("I am happy with the result", "POS"),
    ("Sad and disappointed", "NEG"),
    ("Excellent work", "POS"),
    ("Bad quality", "NEG"),
    ("It's okay", "POS"),   # zero hits no léxico -> régua ABSTÉM (abstenção honesta é rastreada)
    ("Hate it", "NEG"),
]


def gold_fn() -> "dict[str, str]":
    return {f"sent::{i:02d}": label for i, (_, label) in enumerate(GOLD_ITEMS)}


def items_fn() -> "list[dict]":
    return [{"key": f"sent::{i:02d}", "text": text} for i, (text, _) in enumerate(GOLD_ITEMS)]


# ── Régua determinística NAIVE (fraca de propósito: sem negação, sem contexto) ────────────
POSITIVE_WORDS = {"good", "great", "love", "excellent", "happy"}
NEGATIVE_WORDS = {"bad", "awful", "hate", "terrible", "sad", "never"}


def deterministic_fn(item: dict) -> dict:
    """Conta hits do léxico de cada lado; empate ou zero hits -> abstém (honesto).
    Não entende negação nem contexto — exatamente o tipo de régua barata cujos pontos
    cegos o shadow-audit existe para expor."""
    text = item["text"].lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos > neg:
        label = "POS"
    elif neg > pos:
        label = "NEG"
    else:
        label = None
    return {"label": label, "abstain": label is None,
            "raw": f"régua naive: pos={pos} neg={neg} -> {label}"}


# ── Agente: painel de modelos (roster por env; ver docstring do módulo) ───────────────────
def make_agent_fn(budget_usd: float):
    """Factory do agente pago. Fail-fast na construção se o roster estiver vazio (mesma
    política dos factories do pacote); orçamento acumulado num closure entre chamadas.

    Provider-agnóstica: resolve o provider ATIVO uma vez (env AI_SQUAD_PROVIDER; default
    openrouter) e passa pro factory de job. Painel inteiro no Qwen Cloud = só trocar a env."""
    roster = squad_roster("sentiment_judge")
    if not roster:
        raise RuntimeError(
            "roster vazio p/ sentiment_judge — configure a env "
            'AI_SQUAD_ROSTER_SENTIMENT_JUDGE="slug:pin:pout[,slug2:pin2:pout2]" '
            "(preços em USD/Mtok; catálogo vivo em https://openrouter.ai/models — no Qwen Cloud, "
            "https://www.alibabacloud.com/help/en/model-studio/models)")
    provider = default_provider()
    spent = {"total": 0.0}

    def agent(item: dict) -> "Optional[dict]":
        remaining = budget_usd - spent["total"]
        if remaining <= 0:
            return None  # sem-resposta LIMPA por teto (o motor conta como no_answer, não erro)
        jobs = [
            make_text_job(
                key=f"{item['key']}::{slug}",
                prompt=("Classify the sentiment of the following text as positive or negative.\n"
                        "Respond with exactly one word: POS or NEG.\n"
                        f"Text: {item['text']}"),
                model=slug, price_in_per_mtok=pin, price_out_per_mtok=pout,
                system="You are a sentiment classifier. Output only POS or NEG.",
                temperature=0.0, timeout=60, provider=provider,
            )
            for slug, pin, pout in roster
        ]
        report = run_squad(jobs, workers=len(jobs), budget_usd=remaining)
        spent["total"] += report.total_cost_usd
        # JobResults CRUS entram no agregador (erro/skip não vota — n_valid conta só os ok);
        # montar painel na mão e dar veredito default a erro seria contaminar o voto.
        agg = aggregate_panel_verdicts(report.results, keywords=("POS", "NEG"), default="NEG")
        if agg["n_valid"] == 0:
            return None  # painel inteiro fora do ar = sem resposta, não um voto "NEG"
        return {"label": agg["verdict"], "cost_usd": report.total_cost_usd,
                "raw": f"painel n_valid={agg['n_valid']} consensus={agg['consensus']}: "
                       f"{[(p['model'], p['verdict']) for p in agg['panel']]}"}

    return agent


# ── Wiring: papel no fiscal + workflow no maestro ─────────────────────────────────────────
def spec_factory() -> RoleAuditSpec:
    return RoleAuditSpec(role="sentiment_judge", items_fn=items_fn,
                         deterministic_fn=deterministic_fn, make_agent_fn=make_agent_fn,
                         gold_fn=gold_fn)


register_role("sentiment_judge", spec_factory)
register(WorkflowSpec(
    name="shadow_sentiment_judge", roles=("sentiment_judge",),
    runner=make_shadow_runner("sentiment_judge"), default_budget_usd=0.02,
    description="shadow do juiz de sentimento toy: régua de léxico vs painel de modelos vs gold humano"))


if __name__ == "__main__":
    raise SystemExit(maestro_main())
