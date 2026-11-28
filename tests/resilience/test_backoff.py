"""Intervalo entre tentativas, medido pelos horários de recebimento no provider.

O backoff tem jitter (0 a 0,75 s), então os testes verificam faixas, nunca valores exatos.
Em erro imediato a duração da tentativa é ~0, e a diferença entre horários é a pausa
mais o overhead do gateway.
"""

from datetime import datetime

import pytest

OVERHEAD = 0.6  # folga para o gateway e a rede local


def _gap(calls):
    first, second = (datetime.fromisoformat(c["ts"]) for c in calls)
    return (second - first).total_seconds()


@pytest.mark.parametrize("feature", ["F1", "F2"])
def test_error_500_waits_exponential_base_plus_jitter(stack, feature):
    stack.set_mode(feature, "error_500")
    stack.run(feature)

    assert 0.5 <= _gap(stack.calls()) <= 0.5 + 0.75 + OVERHEAD


@pytest.mark.parametrize("feature", ["F4", "F3"])
def test_error_429_honors_retry_after(stack, feature):
    stack.set_mode(feature, "error_429")  # o provider envia Retry-After: 2
    stack.run(feature)

    assert 2.0 <= _gap(stack.calls()) <= 2.0 + 0.75 + OVERHEAD
