"""Provider travado ou lento: tentativa cortada e resposta explícita, não o 504 da borda."""

import pytest

# feature -> (tentativas, mínimo e máximo de segundos): timeout por tentativa + pausas.
EXPECTED = {
    "F1": (2, 6.0, 10.0),
    "F4": (2, 6.0, 10.0),
    "F2": (1, 19.5, 23.0),
    "F3": (1, 11.5, 14.5),
}


@pytest.mark.parametrize("feature", list(EXPECTED))
def test_hung_provider_returns_explicit_error_in_time(stack, feature):
    attempts, minimum, maximum = EXPECTED[feature]
    stack.set_mode(feature, "timeout")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert response.json()["code"] == "model_timeout"  # JSON da app, não o HTML do nginx
    assert minimum <= seconds <= maximum
    assert len(stack.calls()) == attempts


@pytest.mark.parametrize("feature", ["F1", "F4"])
def test_slow_provider_beyond_attempt_timeout_fails_within_15s(stack, feature):
    stack.set_mode(feature, "slow")

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert seconds <= 15
    assert len(stack.calls()) == 2


@pytest.mark.parametrize("feature,limit", [("F1", 3.0), ("F4", 3.0), ("F2", 20.0), ("F3", 14.0)])
def test_normal_operation_is_not_interrupted_nor_retried(stack, feature, limit):
    response, seconds = stack.run(feature)

    assert response.status_code == 200
    assert seconds <= limit
    assert [c["status"] for c in stack.calls()] == [200]
