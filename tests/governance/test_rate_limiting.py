"""Limite de requisições por chave (RPM) no gateway (ADR 0010).

Semântica observada no LiteLLM v1.102.1 (limitador v3, contador em memória do gateway):
janela FIXA de 60 s que começa na primeira requisição admitida; recusas não abrem nem
estendem a janela; cada requisição recebida conta 1, por mais tentativas físicas que gere.
"""

import concurrent.futures
import time

from conftest import CLA_L, GPT_L, error_type

RPM = 3


def test_dentro_do_limite_encaminha_e_informa_o_saldo(gov):
    key = gov.new_key(max_budget=5.0, rpm_limit=RPM)
    remaining = []
    for _ in range(RPM):
        response = gov.chat(key)
        assert response.status_code == 200
        remaining.append(int(response.headers["x-ratelimit-api_key-remaining-requests"]))
    assert remaining == [2, 1, 0]
    assert gov.count() == RPM


def test_requisicao_alem_do_limite_recusada_antes_do_provider(gov):
    key = gov.new_key(max_budget=5.0, rpm_limit=RPM)
    gov.exhaust_rpm(key, RPM)
    response = gov.refused_without_provider_call(key)
    assert response.status_code == 429
    assert error_type(response) == "throttling_error"
    assert response.json()["error"]["message"].startswith("Rate limit exceeded for")
    assert response.headers["retry-after"] == "60"


def test_conta_requisicao_logica_e_nao_tentativa_fisica(gov):
    # Primário e equivalente em 500: cada requisição vira 4 chamadas (2 + 1 + mini) e gasta 1.
    key = gov.new_key(max_budget=5.0, rpm_limit=RPM)
    gov.fail(GPT_L, "error_500")
    gov.fail(CLA_L, "error_500")
    response = gov.chat(key)
    assert response.status_code == 200
    assert gov.count() == 4
    assert response.headers["x-ratelimit-api_key-remaining-requests"] == "2"


def test_concorrencia_respeita_o_limite(gov):
    key = gov.new_key(max_budget=5.0, rpm_limit=RPM)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        statuses = [r.status_code for r in pool.map(lambda _: gov.chat(key), range(6))]
    assert statuses.count(200) == RPM
    assert statuses.count(429) == 6 - RPM
    assert gov.count() == RPM


def test_recupera_quando_a_janela_termina(gov):
    key = gov.new_key(max_budget=5.0, rpm_limit=RPM)
    opened = time.monotonic()
    gov.exhaust_rpm(key, RPM)
    gov.refused_without_provider_call(key)
    # Antes do fim da janela continua recusando, mesmo com recusas no meio.
    time.sleep(max(0.0, opened + 50 - time.monotonic()))
    gov.refused_without_provider_call(key)
    # Depois de 60 s da PRIMEIRA requisição a janela é nova (não 60 s depois da recusa).
    time.sleep(max(0.0, opened + 62 - time.monotonic()))
    before = gov.count()
    response = gov.chat(key)
    assert response.status_code == 200
    assert gov.count() == before + 1
