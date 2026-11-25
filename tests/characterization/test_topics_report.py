"""F3: relatório de tópicos por período (POST /reports/topics).

Só períodos pequenos: um dia (137 tickets, ~10 s) e um período sem tickets.
O mês inteiro passa dos 30 s da borda (dor já diagnosticada) e não é
caracterizado aqui como sucesso.
"""

import pytest

URL = "/reports/topics"


def test_relatorio_de_um_dia(client, load_golden):
    # Arrange
    esperado = load_golden("topics_2026-08-01")

    # Act
    resp = client.post(URL, json=esperado["request"])

    # Assert: total, ordem dos tópicos, contagens e exemplos
    assert resp.status_code == esperado["status"], resp.text
    assert resp.json() == esperado["body"]


def test_periodo_sem_tickets(client):
    resp = client.post(URL, json={"start": "2026-09-01", "end": "2026-09-30"})

    assert resp.status_code == 200
    assert resp.json() == {"start": "2026-09-01", "end": "2026-09-30",
                           "total_tickets": 0, "topics": []}


@pytest.mark.parametrize("payload, detail", [
    pytest.param({"start": "2026-08-10", "end": "2026-08-01"},
                 {"detail": "A data inicial é posterior à data final"},
                 id="inicio-depois-do-fim"),
    pytest.param({"start": "2026-08-01"}, {"detail": [
        {"type": "missing", "loc": ["body", "end"], "msg": "Field required",
         "input": {"start": "2026-08-01"}},
    ]}, id="sem-data-final"),
    pytest.param({"start": "2026-13-01", "end": "2026-08-01"}, {"detail": [
        {"type": "date_from_datetime_parsing", "loc": ["body", "start"],
         "msg": "Input should be a valid date or datetime, month value is outside expected range of 1-12",
         "input": "2026-13-01", "ctx": {"error": "month value is outside expected range of 1-12"}},
    ]}, id="mes-invalido"),
    pytest.param({"start": "01/08/2026", "end": "2026-08-01"}, {"detail": [
        {"type": "date_from_datetime_parsing", "loc": ["body", "start"],
         "msg": "Input should be a valid date or datetime, invalid character in year",
         "input": "01/08/2026", "ctx": {"error": "invalid character in year"}},
    ]}, id="formato-brasileiro"),
])
def test_rejeita_periodo_invalido(client, payload, detail):
    resp = client.post(URL, json=payload)

    assert resp.status_code == 422
    assert resp.json() == detail
