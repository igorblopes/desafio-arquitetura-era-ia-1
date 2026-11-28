"""Contrato de saída de F1 e F4 diante de respostas do modelo fora do formato (em processo).

O provider-fake é determinístico e sempre devolve JSON correto, então estes casos não
aparecem pela borda. Um LLM real produz todos eles (JSON entre cercas de markdown, campo
faltando, tipo errado). A regra é a mesma do enunciado: saída fora do contrato vira erro
explícito (502, o "upstream" respondeu algo inválido), nunca um 200 inventado, nunca um
`null` que finge ausência legítima de informação e nunca um 500 genérico com stack trace.

O modelo substituto implementa o mesmo contrato `ports.LanguageModel` que o adapter.
"""

import json

import pytest
from fastapi.testclient import TestClient

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"


class FixedOutput:
    """LanguageModel que devolve sempre o mesmo texto (o que o "modelo" respondeu)."""

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def complete(self, capability: str, prompt: str):
        self.calls += 1
        return self.text


def call(helpdesk, monkeypatch, route: str, output) -> tuple[int, dict | str]:
    model = FixedOutput(output)
    monkeypatch.setattr(helpdesk, "language_model", model)
    client = TestClient(helpdesk.app, raise_server_exceptions=False)
    response = client.post(route, json={"ticket_id": "TK-00042", "text": T42})
    assert model.calls == 1  # um pedido ao modelo; nenhuma repetição na feature
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


# ------------------------------------------------------------------ F1

F1 = "/tickets/classification"


def test_f1_saida_valida(helpdesk, monkeypatch):
    status, body = call(helpdesk, monkeypatch, F1, '{"category": "delivery", "priority": "high"}')
    assert (status, body) == (200, {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"})


def test_f1_preserva_ticket_id_original_mesmo_se_o_modelo_devolver_outro(helpdesk, monkeypatch):
    output = '{"ticket_id": "TK-99999", "category": "delivery", "priority": "high"}'
    status, body = call(helpdesk, monkeypatch, F1, output)
    assert (status, body) == (200, {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"})


@pytest.mark.parametrize("output", [
    pytest.param('```json\n{"category": "delivery", "priority": "high"}\n```', id="json-entre-cercas"),
    pytest.param("Categoria: delivery", id="texto-livre"),
    pytest.param("[]", id="json-lista"),
    pytest.param(None, id="conteudo-nulo"),
    pytest.param('{"category": "entrega", "priority": "high"}', id="categoria-fora-do-enum"),
    pytest.param('{"category": "delivery", "priority": "urgent"}', id="prioridade-fora-do-enum"),
    pytest.param('{"category": ["delivery"], "priority": "high"}', id="categoria-lista"),
    pytest.param('{"priority": "high"}', id="sem-categoria"),
])
def test_f1_saida_fora_do_contrato_vira_502_explicito(helpdesk, monkeypatch, output):
    status, body = call(helpdesk, monkeypatch, F1, output)
    assert status == 502, body
    assert isinstance(body, dict) and set(body) == {"detail"}


# ------------------------------------------------------------------ F4

F4 = "/tickets/extraction"


@pytest.mark.parametrize("output, expected", [
    pytest.param({"order_number": "#481516", "product": "teclado mecânico"},
                 {"order_number": "#481516", "product": "teclado mecânico"}, id="pedido-e-produto"),
    pytest.param({"order_number": None, "product": "aspirador robô"},
                 {"order_number": None, "product": "aspirador robô"}, id="pedido-ausente"),
    pytest.param({"order_number": "#481516", "product": None},
                 {"order_number": "#481516", "product": None}, id="produto-ausente"),
    # Ausência LEGÍTIMA: o modelo respondeu e disse explicitamente que não há nada.
    pytest.param({"order_number": None, "product": None},
                 {"order_number": None, "product": None}, id="ambos-ausentes"),
])
def test_f4_saida_valida_inclusive_nulos_legitimos(helpdesk, monkeypatch, output, expected):
    status, body = call(helpdesk, monkeypatch, F4, json.dumps(output, ensure_ascii=False))
    assert (status, body) == (200, {"ticket_id": "TK-00042", **expected})


@pytest.mark.parametrize("output", [
    # Campos faltando NÃO são ausência legítima: viraria {"order_number": null, ...} fictício.
    pytest.param("{}", id="objeto-vazio"),
    pytest.param('{"order_number": "#481516"}', id="sem-produto"),
    pytest.param('{"product": "teclado mecânico"}', id="sem-pedido"),
    # Formato do número: '#' + exatamente 6 dígitos ASCII, nada depois.
    pytest.param('{"order_number": "#481516\\n", "product": null}', id="pedido-com-quebra-de-linha"),
    pytest.param('{"order_number": "#\\u0664\\u0668\\u0661\\u0665\\u0661\\u0666", "product": null}',
                 id="pedido-com-digitos-nao-ascii"),
    pytest.param('{"order_number": "481516", "product": null}', id="pedido-sem-cerquilha"),
    pytest.param('{"order_number": 481516, "product": null}', id="pedido-numerico"),
    pytest.param('{"order_number": "#481516", "product": 123}', id="produto-numerico"),
    pytest.param('```json\n{"order_number": "#481516", "product": null}\n```', id="json-entre-cercas"),
    pytest.param("[]", id="json-lista"),
    pytest.param(None, id="conteudo-nulo"),
])
def test_f4_saida_fora_do_contrato_vira_502_explicito(helpdesk, monkeypatch, output):
    status, body = call(helpdesk, monkeypatch, F4, output)
    assert status == 502, body
    assert isinstance(body, dict) and set(body) == {"detail"}
