"""Provider travado ou lento: tentativa cortada e resposta explícita, não o 504 da borda.

Passo 11 (ADR 0006): com fallback, só o esgotamento da cadeia inteira gera erro; por isso
os dois providers inteiros travam. Timeout não é repetido no mesmo destino: cada destino
leva no máximo o seu timeout por tentativa.
"""

import pytest

# feature -> (chamadas, mínimo e máximo de segundos)
#   F1: 3 + 3 + 2 (gpt L, claude L, gpt mini); F4: 3 + 3.
#   F2: o deadline da app (25 s) corta a cadeia; F3: 12 + 12 = 24 s, o gateway desiste antes.
EXPECTED = {
    "F1": (3, 7.5, 10.0),
    "F4": (2, 5.5, 8.0),
    "F2": (2, 24.5, 27.0),
    "F3": (2, 23.5, 26.0),
}


@pytest.mark.parametrize("feature", list(EXPECTED))
def test_hung_provider_returns_explicit_error_in_time(stack, feature):
    calls, minimum, maximum = EXPECTED[feature]
    stack.set_all("timeout")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert response.json()["code"] == "model_timeout"  # JSON da app, não o HTML do nginx
    assert minimum <= seconds <= maximum
    assert len(stack.calls(feature)) == calls
    if feature == "F2":
        # a app desistiu, mas o gateway ainda chama o mini (cadeia órfã): espera terminar
        stack.wait_calls(feature, 3, limit=25)
        assert len(stack.calls(feature)) == 3


@pytest.mark.parametrize("feature,calls", [("F1", 3), ("F4", 2)])
def test_slow_provider_beyond_attempt_timeout_fails_within_15s(stack, feature, calls):
    stack.set_all("slow")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert seconds <= 15
    assert len(stack.calls(feature)) == calls


@pytest.mark.parametrize("feature,limit", [("F1", 3.0), ("F4", 3.0), ("F2", 20.0), ("F3", 14.0)])
def test_normal_operation_is_not_interrupted_nor_retried(stack, feature, limit):
    response, seconds = stack.run(feature)

    assert response.status_code == 200
    assert seconds <= limit
    assert [c["status"] for c in stack.calls()] == [200]
