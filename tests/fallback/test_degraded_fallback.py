"""Fallback com modelo inferior: só F1 e F2 aceitam; F3 e F4 falham explicitamente (ADR 0006).

Os dois large ficam em falha POR MODELO, então os mini continuam disponíveis: uma feature
que rejeita degradação não pode chamá-los.
"""

import pytest

from conftest import FEATURES, MINI, PRIMARY_ATTEMPTS_500, chain

CATEGORIES = {"delivery", "payment", "exchange_return", "product_defect", "other"}
PRIORITIES = {"low", "medium", "high"}


@pytest.mark.parametrize("feature", ["F1", "F2"])
def test_accepting_features_use_the_approved_mini_only_after_both_large(stack, feature):
    primary, equivalent, degraded = chain(feature)
    stack.fail_both_large()

    response, seconds = stack.run(feature)

    assert response.status_code == 200
    assert stack.sequence(feature) == (
        [(primary, 500)] * PRIMARY_ATTEMPTS_500 + [(equivalent, 500), (degraded, 200)])
    body = response.json()
    if feature == "F1":  # contrato: valores permitidos
        assert set(body) == {"ticket_id", "category", "priority"}
        assert body["category"] in CATEGORIES and body["priority"] in PRIORITIES
    else:  # sugestão menor, mas texto utilizável pelo atendente
        assert set(body) == {"ticket_id", "suggestion"}
        assert 0 < len(body["suggestion"]) < len(FEATURES["F2"][4]["suggestion"])
    assert seconds <= {"F1": 5, "F2": 8}[feature]


@pytest.mark.parametrize("feature", ["F3", "F4"])
def test_rejecting_features_fail_explicitly_and_never_call_a_mini(stack, feature):
    primary, equivalent = chain(feature)
    stack.fail_both_large()

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert response.json() == {"detail": "O modelo está indisponível.", "code": "model_unavailable"}
    assert stack.sequence(feature) == [(primary, 500)] * PRIMARY_ATTEMPTS_500 + [(equivalent, 500)]
    assert not {c["model"] for c in stack.calls()} & MINI
    assert seconds <= 5


def test_mini_is_never_used_when_a_large_answers(stack):
    for feature in ("F1", "F4"):
        stack.fail(chain(feature)[0], "error_500")
        stack.run(feature)
    assert not {c["model"] for c in stack.calls()} & MINI
