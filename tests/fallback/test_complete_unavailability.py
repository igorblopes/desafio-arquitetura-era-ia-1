"""Indisponibilidade completa: os dois providers inteiros em falha (large e mini).

A cadeia tem de terminar de forma previsível: número exato de chamadas, sem ciclo, erro
explícito da app (JSON com `code`) e nunca o 504 da borda.
"""

import pytest

from conftest import FEATURES, PRIMARY_ATTEMPTS_500, chain


@pytest.mark.parametrize("feature", list(FEATURES))
def test_every_destination_failing_ends_the_chain_with_an_explicit_503(stack, feature):
    stack.fail_both_providers("error_500")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert response.json()["code"] == "model_unavailable"
    destinations = chain(feature)
    expected = [(destinations[0], 500)] * PRIMARY_ATTEMPTS_500 + [(d, 500) for d in destinations[1:]]
    assert stack.sequence(feature) == expected  # 4 chamadas na F1/F2, 3 na F3/F4, sem ciclo
    assert seconds <= 5


@pytest.mark.parametrize("feature,calls,maximum", [("F1", 3, 10.0), ("F4", 2, 8.0)])
def test_every_destination_hung_fails_in_time_without_retrying_timeouts(stack, feature, calls, maximum):
    stack.fail_both_providers("timeout")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert response.json()["code"] == "model_timeout"  # JSON da app, não o HTML do nginx
    assert seconds <= maximum
    assert [c["model"] for c in stack.calls(feature)] == chain(feature)[:calls]
