"""Testes herméticos do bench (bench.py). Zero rede: `make_job_fn` injetado devolve Jobs com
respostas canned; o motor real `run_squad` (puro) roda por cima."""
from super_squad.squad import Job
from super_squad.bench import BenchTask, run_bench, bench_plan, render_markdown
from super_squad.rulers import numeric_close_ruler

POOL = [("lab/cheap", 0.10, 0.20), ("lab/pricey", 1.0, 2.0)]


def _fake_make_job(responses: dict, cost_by_model: dict):
    """Fábrica de Job hermética: run() devolve ({"model","text"}, custo) sem tocar a rede."""
    def mk(*, key, prompt, model, price_in_per_mtok, price_out_per_mtok,
           system=None, temperature=0.2, api_key=None, timeout=120):
        text, cost = responses[key], cost_by_model[model]

        def run():
            return ({"model": model, "text": text}, cost)

        return Job(key=key, run=run, model=model)
    return mk


def test_bench_plan_conta_celulas():
    p = bench_plan([BenchTask("a", "xx"), BenchTask("b", "yy")], POOL, budget_usd=0.5)
    assert p["n_cells"] == 4 and p["rough_cost_estimate_usd"] > 0


def test_dry_run_nao_gasta():
    rep = run_bench([BenchTask("x", "p")], POOL, execute=False)
    assert rep["ran"] is False and rep["plan"]["n_cells"] == 2


def test_matriz_regua_objetiva_e_sugestao():
    task = BenchTask("num", "quanto?", ruler=numeric_close_ruler(0.0), gold=1050)
    responses = {"num::lab/cheap": "logo da 1050 grafts", "num::lab/pricey": "acho que 999"}
    costs = {"lab/cheap": 0.0001, "lab/pricey": 0.002}
    rep = run_bench([task], POOL, execute=True, make_job_fn=_fake_make_job(responses, costs))
    assert rep["ran"] is True and rep["n_ok"] == 2
    m = rep["matrix"]["num"]
    assert m["lab/cheap"]["quality"]["pass"] is True
    assert m["lab/pricey"]["quality"]["pass"] is False
    # sugestão: quem reprovou na régua sai; sobra só o cheap
    sug = rep["suggested_roster"]["by_role"]["num"]
    assert [s["slug"] for s in sug] == ["lab/cheap"]


def test_ratings_de_varios_colaboradores_viram_qualidade():
    task = BenchTask("prosa", "escreva")  # SEM régua -> qualidade vem da experiência humana
    responses = {"prosa::lab/cheap": "texto A", "prosa::lab/pricey": "texto B"}
    costs = {"lab/cheap": 0.001, "lab/pricey": 0.001}
    ratings = {"prosa": {"lab/cheap": [9, 8, 9], "lab/pricey": [5, 6]}}
    rep = run_bench([task], POOL, execute=True, ratings=ratings,
                    make_job_fn=_fake_make_job(responses, costs))
    qc = rep["matrix"]["prosa"]["lab/cheap"]["quality"]
    qp = rep["matrix"]["prosa"]["lab/pricey"]["quality"]
    assert qc["human_score"] == 9.0 and qc["score01"] == 0.9   # mediana [9,8,9]=9
    assert qp["human_score"] == 5.5                            # mediana [5,6]=5.5
    # leaderboard ordena por qualidade: cheap (0.9) acima de pricey (0.55)
    assert rep["leaderboard"]["prosa"][0]["slug"] == "lab/cheap"


def test_sem_regua_nem_rating_vira_human_review():
    responses = {"q::lab/cheap": "a", "q::lab/pricey": "b"}
    costs = {"lab/cheap": 0.001, "lab/pricey": 0.001}
    rep = run_bench([BenchTask("q", "p")], POOL, execute=True,
                    make_job_fn=_fake_make_job(responses, costs))
    q = rep["matrix"]["q"]["lab/cheap"]["quality"]
    assert q["graded"] is False and q["score01"] is None


def test_preflight_bloqueia_slug_ausente_no_catalogo():
    catalog = {"data": [{"id": "lab/cheap",
                         "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}}]}
    rep = run_bench([BenchTask("q", "p")], POOL, execute=True, preflight=True,
                    list_models_fn=lambda: catalog,
                    make_job_fn=_fake_make_job({"q::lab/cheap": "a", "q::lab/pricey": "b"},
                                               {"lab/cheap": 0.001, "lab/pricey": 0.001}))
    assert rep["ok"] is False and "lab/pricey" in rep["error"]


def test_render_markdown_nao_quebra():
    task = BenchTask("num", "q", ruler=numeric_close_ruler(0.0), gold=1050)
    rep = run_bench([task], POOL, execute=True,
                    make_job_fn=_fake_make_job(
                        {"num::lab/cheap": "1050", "num::lab/pricey": "1050"},
                        {"lab/cheap": 0.0001, "lab/pricey": 0.002}))
    md = render_markdown(rep)
    assert "Bench" in md and "Custo" in md and "Pontuação por função" in md
    assert "DRY-RUN" in render_markdown(run_bench([task], POOL, execute=False))
