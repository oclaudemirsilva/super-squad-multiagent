"""demo/toy_army.py — prova de plumbing do exército: 1 persona single-shot (do catálogo
vendorizado) rodando via OpenRouter, gerida pelo motor `run_squad` com teto de gasto.

NÃO é medição de roster (o slug aqui é escolhido à mão só pra provar a esteira; roteamento
MEDIDO é o candidate_eval com ground-truth, fase seguinte). Roda de verdade → gasta $ real
(centavos). Exige OPENROUTER_API_KEY no env.

    OPENROUTER_API_KEY=... python -m demo.toy_army \
        --role roles/vendor/security-auditor.md \
        --slug deepseek/deepseek-chat --budget 0.05
"""
from __future__ import annotations

import argparse
import os
import sys

from super_squad import roles
from super_squad.squad import run_squad

SAMPLE_INPUT = (
    "Audit this endpoint for security issues and list findings by severity:\n\n"
    "    @app.route('/login', methods=['POST'])\n"
    "    def login():\n"
    "        u = request.form['user']; p = request.form['pass']\n"
    "        q = \"SELECT * FROM users WHERE user='%s' AND pass='%s'\" % (u, p)\n"
    "        row = db.execute(q).fetchone()\n"
    "        if row: session['uid'] = row['id']; return redirect('/home')\n"
    "        return 'bad login'\n"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default="roles/vendor/security-auditor.md")
    ap.add_argument("--slug", default="deepseek/deepseek-chat")
    ap.add_argument("--pin", type=float, default=0.14)
    ap.add_argument("--pout", type=float, default=0.28)
    ap.add_argument("--budget", type=float, default=0.05)
    args = ap.parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERRO: OPENROUTER_API_KEY ausente no env.", file=sys.stderr)
        return 2

    spec = roles.load_role(args.role)
    print(f"papel: {spec.name}  | single_shot={spec.single_shot}  | tools={spec.declared_tools}")
    print(f"modelo: {args.slug}  | teto: ${args.budget}\n")

    job = roles.make_role_job(
        spec.name, spec, SAMPLE_INPUT, args.slug, args.pin, args.pout,
    )

    events: list = []
    report = run_squad([job], workers=1, budget_usd=args.budget, on_event=events.append)

    r = report.results[0]
    if r.error:
        print(f"FALHOU: {r.error}", file=sys.stderr)
        return 1
    print("=== VEREDITO DO PAPEL (real, via OpenRouter) ===")
    print(r.value["text"])
    print(f"\n=== custo real: ${report.total_cost_usd:.6f}  | ok={report.n_ok} err={report.n_error} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
