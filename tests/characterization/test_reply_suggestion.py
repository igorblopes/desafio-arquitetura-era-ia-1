"""F2: sugestão de resposta (POST /tickets/reply-suggestion).

O texto completo é comparado com um golden master (expected/*.json) gravado a
partir de respostas reais observadas pela borda. Cada chamada leva ~16 s,
abaixo dos 30 s da borda.
"""

import pytest

URL = "/tickets/reply-suggestion"


@pytest.mark.parametrize("golden", [
    "reply_suggestion_TK-00042",   # entrega atrasada
    "reply_suggestion_TK-00100",   # cobrança duplicada
])
def test_sugere_resposta_com_texto_integral(client, load_golden, golden):
    # Arrange
    esperado = load_golden(golden)

    # Act
    resp = client.post(URL, json=esperado["request"])

    # Assert: status e corpo inteiro, inclusive o texto da sugestão byte a byte
    assert resp.status_code == esperado["status"], resp.text
    assert resp.json() == esperado["body"]


@pytest.mark.parametrize("payload, detail", [
    pytest.param({"ticket_id": "TK-1"}, {"detail": [
        {"type": "missing", "loc": ["body", "text"], "msg": "Field required",
         "input": {"ticket_id": "TK-1"}},
    ]}, id="sem-texto"),
    pytest.param({"ticket_id": "", "text": "x"}, {"detail": [
        {"type": "string_too_short", "loc": ["body", "ticket_id"],
         "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}},
    ]}, id="ticket-id-vazio"),
])
def test_rejeita_entrada_invalida(client, payload, detail):
    resp = client.post(URL, json=payload)

    assert resp.status_code == 422
    assert resp.json() == detail
