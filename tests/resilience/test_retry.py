"""Limite de tentativas, recuperação e ausência de amplificação, pelo /admin/calls."""

import pytest

from conftest import FEATURES

MAX_ATTEMPTS = 2  # 1 tentativa + 1 retentativa (gateway/config.yaml)


@pytest.mark.parametrize("mode", ["error_500", "error_429"])
@pytest.mark.parametrize("feature", list(FEATURES))
def test_persistent_failure_makes_exactly_two_attempts(stack, feature, mode):
    stack.set_mode(feature, mode)

    response, seconds = stack.run(feature)

    assert response.status_code == 503
    assert seconds <= 15
    calls = stack.calls()
    assert len(calls) == MAX_ATTEMPTS  # 4 indicaria retry também no SDK da app
    _, _, provider, model = FEATURES[feature]
    assert {(c["provider"], c["model"]) for c in calls} == {(provider, model)}  # sem fallback


@pytest.mark.parametrize(
    "feature,mode",
    [("F1", "error_500"), ("F4", "error_429"), ("F1", "timeout"), ("F2", "error_500")],
)
def test_transient_failure_is_recovered_by_retry(stack, feature, mode):
    response, _ = stack.run_recovering(feature, mode)

    assert response.status_code == 200
    calls = stack.calls()
    assert len(calls) == 2
    assert calls[0]["status"] != 200 and calls[1]["status"] == 200
