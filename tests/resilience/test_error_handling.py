"""Erros não recuperáveis não são repetidos e nada interno vaza para o consumidor."""


def test_invalid_input_never_reaches_the_provider(stack):
    response = stack.edge.post("/tickets/classification", json={"ticket_id": "TK-1"})

    assert response.status_code == 422
    assert stack.calls() == []


def test_provider_400_is_not_retried_and_becomes_502(stack):
    huge = {"ticket_id": "TK-1", "text": "pedido atrasado " * 2500}  # acima do contexto

    response = stack.edge.post("/tickets/classification", json=huge)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "A requisição ao modelo foi recusada.",
        "code": "model_rejected",
    }
    assert [c["status"] for c in stack.calls()] == [400]


def test_error_body_does_not_leak_internals(stack):
    stack.set_mode("F1", "error_500")

    response, _ = stack.run("F1")

    assert set(response.json()) == {"detail", "code"}
    text = response.text.lower()
    for secret in ("litellm", "openai", "gpt-fake", "sk-", "gateway:4000", "traceback"):
        assert secret not in text
