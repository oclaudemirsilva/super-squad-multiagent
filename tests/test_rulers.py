"""Testes herméticos das réguas determinísticas (rulers.py). Zero rede, puros."""
from super_squad.rulers import (
    json_valid_ruler, numeric_close_ruler, length_window_ruler, contains_all_ruler,
    exact_match_ruler, keyword_verdict_ruler, set_f1_ruler, resolve_ruler,
    _parse_number, _all_numbers,
)


# ── json_valid ───────────────────────────────────────────────────────────────

def test_json_valid_passa_objeto_limpo():
    r = json_valid_ruler(("sexo", "idade"))
    out = r('{"sexo": "M", "idade": 34}')
    assert out["pass"] is True and out["label"] == "VALID"


def test_json_valid_reprova_cerca_markdown_por_default():
    r = json_valid_ruler()
    out = r('```json\n{"a": 1}\n```')
    assert out["pass"] is False and out["label"] == "INVALID_JSON"


def test_json_valid_allow_fenced_remove_cerca():
    r = json_valid_ruler(allow_fenced=True)
    out = r('```json\n{"a": 1}\n```')
    assert out["pass"] is True and out["detail"]["fenced"] is True


def test_json_valid_reprova_chave_faltando():
    r = json_valid_ruler(("sexo", "idade", "norwood"))
    out = r('{"sexo": "M", "idade": 34}')
    assert out["pass"] is False and out["detail"]["missing"] == ["norwood"]


# ── numeric_close ────────────────────────────────────────────────────────────

def test_numeric_close_acha_resposta_no_meio_do_texto():
    r = numeric_close_ruler(tol=0.0)
    out = r("Logo, a demanda = 30 x 35 = 1050 grafts no total.", gold=1050)
    assert out["pass"] is True and out["score"] == 1050.0


def test_numeric_close_sem_gold_reprova():
    assert numeric_close_ruler()("qualquer coisa", gold=None)["label"] == "NO_GOLD"


def test_numeric_close_nao_casa():
    out = numeric_close_ruler(tol=0.5)("resultado 999", gold=1050)
    assert out["pass"] is False and out["label"] == "NO_MATCH"


def test_parse_number_ptbr():
    assert _parse_number("1.050") == 1050.0
    assert _parse_number("37,5") == 37.5
    assert _parse_number("2.287,50") == 2287.5
    assert _parse_number("0.25") == 0.25


def test_all_numbers_extrai_varios():
    nums = _all_numbers("30 cm2 x 35 = 1.050; oferta 2.250")
    assert 1050.0 in nums and 2250.0 in nums and 35.0 in nums


# ── length_window ────────────────────────────────────────────────────────────

def test_length_window_dentro_e_fora():
    r = length_window_ruler(3, 5)
    assert r("uma duas tres quatro")["pass"] is True
    assert r("uma duas")["label"] == "TOO_SHORT"
    assert r("a b c d e f g")["label"] == "TOO_LONG"


# ── contains_all ─────────────────────────────────────────────────────────────

def test_contains_all_ignora_acento_e_caixa():
    r = contains_all_ruler(("Frontal", "coroa", "área doadora"))
    assert r("tire foto frontal, do topo, da COROA e da area doadora")["pass"] is True


def test_contains_all_reporta_faltantes():
    out = contains_all_ruler(("frontal", "coroa"))("só a frontal aqui")
    assert out["pass"] is False and "coroa" in out["detail"]["missing"]


# ── exact_match ──────────────────────────────────────────────────────────────

def test_exact_match_normaliza():
    assert exact_match_ruler()("  Álcool  ", gold="alcool")["pass"] is True
    assert exact_match_ruler()("outro", gold="alcool")["pass"] is False


# ── keyword_verdict ──────────────────────────────────────────────────────────

def test_keyword_verdict_extrai_e_compara_gold():
    r = keyword_verdict_ruler()
    assert r("no geral BAD, definitivamente")["label"] == "BAD"
    assert r("isso é GOOD", gold="GOOD")["pass"] is True
    assert r("isso é GOOD", gold="BAD")["pass"] is False


# ── set_f1 ───────────────────────────────────────────────────────────────────

def test_set_f1_extracao_de_lista():
    r = set_f1_ruler(threshold=1.0)
    out = r("frontal, coroa, topo", gold=["topo", "frontal", "coroa"])
    assert out["pass"] is True and out["score"] == 1.0


def test_set_f1_parcial_reprova_no_threshold_alto():
    out = set_f1_ruler(threshold=0.9)("frontal", gold=["frontal", "coroa"])
    assert out["pass"] is False and out["detail"]["recall"] == 0.5


# ── resolve_ruler ────────────────────────────────────────────────────────────

def test_resolve_ruler_mapeia_strings():
    assert resolve_ruler(None) is None
    assert resolve_ruler("json_valid:a,b")('{"a":1,"b":2}')["pass"] is True
    assert resolve_ruler("length_window:1:3")("uma duas")["pass"] is True
    assert resolve_ruler("numeric_close:0.0")("=1050", gold=1050)["pass"] is True
    assert resolve_ruler("contains_all:frontal,coroa")("frontal e coroa")["pass"] is True


def test_resolve_ruler_desconhecida_levanta():
    import pytest
    with pytest.raises(ValueError):
        resolve_ruler("regua_que_nao_existe")
