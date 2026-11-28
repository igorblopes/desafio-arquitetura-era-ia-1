"""Limite de tentativas, recuperação e ausência de amplificação, pelo /admin/calls.

Passo 11 (ADR 0006): o retry continua existindo só no destino primário e só para falha
imediata (500/503). 429 e timeout migram direto para o equivalente. Para isolar o retry,
o esgotamento põe os dois providers inteiros em falha.
"""

import pytest

from conftest import FALLBACK_DESTINATIONS, FEATURES

# tentativas no primário por modo: 1 + retentativas da política do primário
PRIMARY_ATTEMPTS = {"error_500": 2, "error_429": 1}


@pytest.mark.parametrize("mode", ["error_500", "error_429"])
@pytest.mark.parametrize("feature", list(FEATURES))
def test_persistent_failure_limits_attempts_per_destination(stack, feature, mode):
    stack.set_all(mode)

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert seconds <= 15
    calls = stack.calls(feature)
    _, _, provider, model = FEATURES[feature]
    on_primary = [c for c in calls if (c["provider"], c["model"]) == (provider, model)]
    assert len(on_primary) == PRIMARY_ATTEMPTS[mode]  # o dobro indicaria retry também no SDK
    # cada destino seguinte: exatamente uma tentativa, e nada além da cadeia
    assert len(calls) == PRIMARY_ATTEMPTS[mode] + FALLBACK_DESTINATIONS[feature]


@pytest.mark.parametrize("feature", ["F1", "F4", "F2"])
def test_transient_failure_is_recovered_by_retry_on_the_same_destination(stack, feature):
    response, _ = stack.run_recovering(feature, "error_500")

    assert response.status_code == 200
    calls = stack.calls(feature)
    assert len(calls) == 2
    assert calls[0]["status"] == 500 and calls[1]["status"] == 200
    assert calls[0]["model"] == calls[1]["model"] == FEATURES[feature][3]  # retry, não fallback
