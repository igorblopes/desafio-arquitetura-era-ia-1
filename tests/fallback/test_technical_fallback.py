"""Fallback técnico: primário large -> large equivalente de OUTRO provider (ADR 0006).

A prova é o /admin/calls, não o HTTP 200: cada teste confere a sequência exata de destinos
e que a resposta é idêntica à do primário (golden master da caracterização).
"""

from datetime import datetime

import pytest

from conftest import FEATURES, LARGE, PRIMARY_ATTEMPTS_500, PROVIDER_OF, chain


@pytest.mark.parametrize("feature", list(FEATURES))
def test_normal_operation_uses_only_the_primary(stack, feature):
    response, _ = stack.run(feature)

    assert response.status_code == 200
    assert response.json() == FEATURES[feature][4]
    assert stack.sequence(feature) == [(chain(feature)[0], 200)]


@pytest.mark.parametrize("feature", list(FEATURES))
def test_primary_500_retries_once_then_recovers_on_the_equivalent_large(stack, feature):
    primary, equivalent = chain(feature)[:2]
    stack.fail(primary, "error_500")

    response, seconds = stack.run(feature)

    assert response.status_code == 200
    assert response.json() == FEATURES[feature][4]  # contrato e conteúdo preservados
    assert stack.sequence(feature) == [(primary, 500)] * PRIMARY_ATTEMPTS_500 + [(equivalent, 200)]
    assert equivalent in LARGE and PROVIDER_OF[equivalent] != PROVIDER_OF[primary]
    assert seconds <= {"F1": 5, "F4": 5, "F2": 22, "F3": 15}[feature]


@pytest.mark.parametrize("feature", ["F1", "F4", "F2"])
def test_primary_429_fails_over_without_retrying_the_saturated_destination(stack, feature):
    primary, equivalent = chain(feature)[:2]
    stack.fail(primary, "error_429")

    response, _ = stack.run(feature)

    assert response.status_code == 200
    assert stack.sequence(feature) == [(primary, 429), (equivalent, 200)]
    first, second = (datetime.fromisoformat(c["ts"]) for c in stack.calls(feature))
    assert (second - first).total_seconds() < 1.0  # não espera o Retry-After de 2 s


def test_f3_fallback_recovers_only_the_failed_batch(stack):
    """Dois lotes (274 tickets): o 1º no primário; a falha começa depois dele. O 2º lote
    vai para o equivalente, o 1º não é refeito e o relatório é igual ao normal."""
    period = {"start": "2026-08-01", "end": "2026-08-02"}
    primary, equivalent = chain("F3")[:2]

    normal, _ = stack.run("F3", period)
    assert normal.status_code == 200
    assert stack.sequence("F3") == [(primary, 200), (primary, 200)]
    stack.reset()

    response, seconds = stack.run_failing_after_first_call("F3", primary, "error_500", period)

    assert response.status_code == 200
    assert response.json() == normal.json()
    assert response.json()["total_tickets"] == 274
    assert stack.sequence("F3") == [(primary, 200), (primary, 500), (primary, 500), (equivalent, 200)]
    assert seconds < 30  # abaixo da borda, sem 504
