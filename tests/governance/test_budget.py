"""Orçamento (hard limit) por chave: recusa no gateway, antes do provider (ADR 0010).

Política de teste igual à da chave governance-budget-demo: US$ 0,0004 e F1 a US$ 0,0001575.
O gateway admite enquanto o gasto acumulado for MENOR que o orçamento, então passam 3
chamadas (a 3ª leva o gasto a 0,0004725, acima do teto) e a 4ª é recusada.
"""

import concurrent.futures
import time

import pytest

from conftest import F1_COST, error_type

BUDGET = 0.0004


def test_consumo_dentro_do_orcamento_e_contabilizado(gov):
    key = gov.new_key(max_budget=BUDGET)
    response = gov.chat(key)
    assert response.status_code == 200
    assert float(response.headers["x-litellm-response-cost"]) == pytest.approx(F1_COST, rel=1e-9)
    assert gov.wait_spend(key, F1_COST) == pytest.approx(F1_COST, rel=1e-9)


def test_esgotamento_e_recusa_antes_do_provider(gov):
    key = gov.new_key(max_budget=BUDGET)
    assert gov.exhaust_budget(key) == 3
    assert gov.count() == 3
    response = gov.refused_without_provider_call(key)
    assert response.status_code == 429
    assert error_type(response) == "budget_exceeded"


def test_gasto_gravado_passa_do_teto_em_no_maximo_uma_chamada(gov):
    # Checagem antes da chamada, custo conhecido só depois: ultrapassa até uma chamada.
    key = gov.new_key(max_budget=BUDGET)
    gov.exhaust_budget(key)
    spend = gov.wait_spend(key, 3 * F1_COST)
    assert spend == pytest.approx(3 * F1_COST, rel=1e-9)
    assert BUDGET < spend < BUDGET + F1_COST


def test_concorrencia_nao_ultrapassa_o_orcamento(gov):
    # O LiteLLM v1.102.1 reserva o custo máximo estimado da requisição em andamento (até
    # 16.384 tokens de saída) e só depois reconcilia: requisições simultâneas veem o saldo
    # já reservado e são recusadas. Conservador, mas o gasto não passa do teto.
    key = gov.new_key(max_budget=BUDGET)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        statuses = [r.status_code for r in pool.map(lambda _: gov.chat(key), range(6))]
    allowed = statuses.count(200)
    assert 1 <= allowed <= 3
    assert set(statuses) <= {200, 429}
    assert gov.count() == allowed
    spend = gov.wait_spend(key, allowed * F1_COST)
    assert spend == pytest.approx(allowed * F1_COST, rel=1e-9)
    assert spend < BUDGET + F1_COST


def test_rajada_sequencial_nunca_passa_de_tres_chamadas(gov):
    # Chamadas coladas na mesma conexão: algumas são recusadas CEDO (reserva da anterior
    # ainda presa), mas o total admitido nunca passa do que o orçamento comporta.
    key = gov.new_key(max_budget=BUDGET)
    statuses = [gov.chat(key).status_code for _ in range(8)]
    time.sleep(1.5)
    statuses += [gov.chat(key).status_code for _ in range(2)]
    assert statuses.count(200) <= 3
    assert gov.count() == statuses.count(200)
    assert gov.exhaust_budget(key, limit=4) == 3 - statuses.count(200)
