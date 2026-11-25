from decimal import Decimal
from fractions import Fraction

import pytest

from metrics.calculations import compute, in_pain_zone, round2


@pytest.mark.parametrize("ca, ce, abstract, total, i, a, d, pain", [
    (0, 0, 0, 0, "0.00", "0.00", "1.00", True),    # isolado sem classes
    (5, 0, 0, 2, "0.00", "0.00", "1.00", True),    # concreto e estável
    (0, 5, 0, 2, "1.00", "0.00", "0.00", False),   # concreto e instável
    (5, 0, 2, 2, "0.00", "1.00", "0.00", False),   # abstrato e estável
    (0, 5, 2, 2, "1.00", "1.00", "1.00", False),   # abstrato e instável
    (2, 2, 1, 2, "0.50", "0.50", "0.00", False),   # equilibrado
], ids=["isolado", "concreto-estavel", "concreto-instavel", "abstrato-estavel",
        "abstrato-instavel", "equilibrado"])
def test_formulas_do_desafio(ca, ce, abstract, total, i, a, d, pain):
    m = compute("x", ca, ce, abstract, total)

    assert (m.ca, m.ce) == (ca, ce)
    assert (str(m.i), str(m.a), str(m.d)) == (i, a, d)
    assert m.pain_zone is pain


def test_dizimas_periodicas_sem_arredondamento_intermediario():
    m = compute("x", ca=2, ce=1, abstract_classes=1, total_classes=3)   # I=1/3, A=1/3

    assert m.i_exact == Fraction(1, 3) and m.a_exact == Fraction(1, 3)
    assert m.d_exact == Fraction(1, 3)
    assert (str(m.i), str(m.a), str(m.d)) == ("0.33", "0.33", "0.33")   # não 0.34


def test_arredondamento_meio_para_cima():
    assert round2(Fraction(1, 8)) == Decimal("0.13")     # round() daria 0.12
    assert round2(Fraction(5, 8)) == Decimal("0.63")
    assert round2(Fraction(2, 3)) == Decimal("0.67")


@pytest.mark.parametrize("a, i, d, expected", [
    ("0.49", "0.00", "0.51", True),
    ("0.00", "0.50", "0.50", False),   # I = 0,5 não é < 0,5
    ("0.50", "0.00", "0.50", False),   # A = 0,5 não é < 0,5
    ("0.25", "0.25", "0.50", True),    # D = 0,5 entra (>=)
    ("0.26", "0.25", "0.49", False),   # D < 0,5
    ("0.00", "0.00", "1.00", True),
])
def test_limites_da_zona_de_dor(a, i, d, expected):
    assert in_pain_zone(Fraction(a), Fraction(i), Fraction(d)) is expected


def test_valor_exato_no_limite_e_sinalizado():
    # I = 1/2 exato: fora da zona (I não é < 0,5) e sem divergência.
    m = compute("x", ca=1, ce=1, abstract_classes=0, total_classes=1)
    assert m.pain_zone is False and m.borderline is False

    # I = 199/400 = 0,4975 -> publicado 0,50: oficial fora; exato dentro.
    m = compute("x", ca=201, ce=199, abstract_classes=0, total_classes=1)
    assert str(m.i) == "0.50"
    assert m.pain_zone is False
    assert m.pain_zone_exact is True
    assert m.borderline is True
