"""Responsabilidade 6: calcular Ca, Ce, I, A, D (fórmulas do desafio).

Os cálculos usam frações exatas; só o resultado final é arredondado para
2 casas (ROUND_HALF_UP). D é calculado de A e I exatos, sem arredondamento
intermediário.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

HALF = Fraction(1, 2)


def instability(ca: int, ce: int) -> Fraction:
    return Fraction(0) if ca + ce == 0 else Fraction(ce, ca + ce)


def abstractness(abstract_classes: int, total_classes: int) -> Fraction:
    return Fraction(0) if total_classes == 0 else Fraction(abstract_classes, total_classes)


def distance(a: Fraction, i: Fraction) -> Fraction:
    return abs(a + i - 1)


def round2(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def in_pain_zone(a, i, d) -> bool:
    """Regra do desafio: A < 0,5 e I < 0,5 e D >= 0,5 (as três juntas)."""
    return a < HALF and i < HALF and d >= HALF


@dataclass(frozen=True)
class ComponentMetrics:
    component: str
    ca: int
    ce: int
    abstract_classes: int
    total_classes: int
    i_exact: Fraction
    a_exact: Fraction
    d_exact: Fraction

    @property
    def i(self) -> Decimal:
        return round2(self.i_exact)

    @property
    def a(self) -> Decimal:
        return round2(self.a_exact)

    @property
    def d(self) -> Decimal:
        return round2(self.d_exact)

    @property
    def pain_zone(self) -> bool:
        """Classificação oficial: sobre os valores publicados (2 casas)."""
        return in_pain_zone(Fraction(self.a), Fraction(self.i), Fraction(self.d))

    @property
    def pain_zone_exact(self) -> bool:
        return in_pain_zone(self.a_exact, self.i_exact, self.d_exact)

    @property
    def borderline(self) -> bool:
        """Arredondamento muda a classificação? (reportado como aviso)."""
        return self.pain_zone != self.pain_zone_exact


def compute(component: str, ca: int, ce: int, abstract_classes: int, total_classes: int) -> ComponentMetrics:
    i = instability(ca, ce)
    a = abstractness(abstract_classes, total_classes)
    return ComponentMetrics(component, ca, ce, abstract_classes, total_classes, i, a, distance(a, i))
