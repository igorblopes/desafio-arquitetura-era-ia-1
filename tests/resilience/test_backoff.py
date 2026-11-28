"""Intervalo entre tentativas, medido pelos horários de recebimento no provider.

O backoff tem jitter (0 a 0,75 s), então os testes verificam faixas, nunca valores exatos.
Em erro imediato a duração da tentativa é ~0, e a diferença entre horários é a pausa
mais o overhead do gateway.

Passo 11 (ADR 0006): o 429 deixou de ser repetido no mesmo destino; com um equivalente
disponível, esperar o Retry-After do provider saturado só atrasaria a recuperação. O teste
de Retry-After virou o teste de que não há pausa antes de migrar.
"""

from datetime import datetime

import pytest

from conftest import FEATURES

OVERHEAD = 0.6  # folga para o gateway e a rede local


def _gap(first: dict, second: dict) -> float:
    return (datetime.fromisoformat(second["ts"]) - datetime.fromisoformat(first["ts"])).total_seconds()


@pytest.mark.parametrize("feature", ["F1", "F2"])
def test_error_500_waits_exponential_base_plus_jitter(stack, feature):
    stack.set_mode(feature, "error_500")
    stack.run(feature)

    first, second = stack.calls(feature)[:2]  # as duas tentativas no primário
    assert first["model"] == second["model"] == FEATURES[feature][3]
    assert 0.5 <= _gap(first, second) <= 0.5 + 0.75 + OVERHEAD


@pytest.mark.parametrize("feature", ["F4", "F3"])
def test_error_429_is_not_retried_and_fails_over_without_waiting(stack, feature):
    stack.set_mode(feature, "error_429")  # o provider envia Retry-After: 2
    stack.run(feature)

    first, second = stack.calls(feature)[:2]
    assert first["status"] == 429 and second["model"] != first["model"]
    assert _gap(first, second) < 2.0  # não esperou o Retry-After
