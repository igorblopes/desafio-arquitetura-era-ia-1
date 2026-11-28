"""Erros não recuperáveis não são repetidos e nada interno vaza para o consumidor.

Passo 11 (ADR 0006): o LiteLLM 1.102.1 dispara o fallback regular para QUALQUER erro, inclusive
400. O bloqueio por `context_window_fallbacks` só vale quando ele reconhece o estouro de
contexto, o que acontece com a mensagem do formato Messages (F2/F3) e não com a do formato
OpenAI em português (F1/F4). O que estes testes garantem: nenhum destino repete um 400, as
tentativas extras falham na hora e o consumidor recebe 502 `model_rejected`.
"""


HUGE = {"ticket_id": "TK-1", "text": "pedido atrasado " * 2500}  # acima do contexto de 8.000


def test_invalid_input_never_reaches_the_provider(stack):
    response = stack.edge.post("/tickets/classification", json={"ticket_id": "TK-1"})

    assert response.status_code == 422
    assert stack.calls() == []


def test_provider_400_is_never_retried_and_becomes_502(stack):
    response = stack.edge.post("/tickets/classification", json=HUGE)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "A requisição ao modelo foi recusada.",
        "code": "model_rejected",
    }
    calls = stack.calls("F1")
    assert {c["status"] for c in calls} == {400}
    models = [c["model"] for c in calls]
    assert len(models) == len(set(models)) <= 3  # um 400 por destino da cadeia, nunca repetido


def test_context_error_recognized_by_the_gateway_does_not_fall_back(stack):
    response = stack.edge.post("/tickets/reply-suggestion", json=HUGE)

    assert response.status_code == 502
    assert [c["status"] for c in stack.calls("F2")] == [400]


def test_error_body_does_not_leak_internals(stack):
    stack.set_all("error_500")

    response, _ = stack.run("F1")

    assert response.status_code == 503
    assert set(response.json()) == {"detail", "code"}
    text = response.text.lower()
    for secret in ("litellm", "openai", "gpt-fake", "claude-fake", "sk-", "gateway:4000",
                   "traceback", "-equivalent", "-degraded"):
        assert secret not in text
