"""Infraestrutura comum dos testes de caracterização da v1 (helpdesk acoplado).

Os testes falam com a aplicação REAL, subida pelo docker compose, sempre pela
borda (edge/nginx), exatamente como um cliente faria. Não há mocks: o
provider-fake responde de verdade e é determinístico no modo `normal`.

Variáveis de ambiente:
  HELPDESK_BASE_URL   URL da borda (padrão http://localhost:8000)
  PROVIDER_ADMIN_URL  URL do provider-fake, usada só para garantir o modo
                      `normal` antes da suíte (padrão http://localhost:8090)
"""

import json
import os
import pathlib

import httpx
import pytest

BASE_URL = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER_ADMIN_URL = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")
EXPECTED_DIR = pathlib.Path(__file__).parent / "expected"

# Maior que o proxy_read_timeout de 30 s da borda: se a borda devolver 504,
# queremos ver o 504, e não um timeout do próprio cliente de teste.
CLIENT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

FAILURE_MODES = ("error_500", "error_429", "timeout", "slow", "midstream_error")


def _valores_texto(obj):
    """Todos os valores string de um JSON aninhado (ignora as chaves)."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _valores_texto(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _valores_texto(v)
    elif isinstance(obj, str):
        yield obj


@pytest.fixture(scope="session", autouse=True)
def ambiente_pronto():
    """Pré-condição da suíte: app saudável e provider-fake em modo normal.

    O /admin/reset devolve o provider ao modo `normal`. Sem isso, um modo de
    falha esquecido por outro experimento faria a suíte falhar por motivo que
    nada tem a ver com o comportamento caracterizado (teste não isolado).
    """
    with httpx.Client(timeout=10.0) as admin:
        try:
            saude = admin.get(f"{BASE_URL}/health")
        except httpx.HTTPError as exc:
            pytest.exit(f"Helpdesk inacessível em {BASE_URL}: {exc}. Rode `docker compose up -d`.", 2)
        assert saude.status_code == 200, saude.text
        assert saude.json() == {"status": "ok"}

        admin.post(f"{PROVIDER_ADMIN_URL}/admin/reset").raise_for_status()
        estado = admin.get(f"{PROVIDER_ADMIN_URL}/admin/failures").json()
        modos = set(_valores_texto(estado))
        assert "normal" in modos, estado
        assert not modos & set(FAILURE_MODES), f"provider-fake fora do modo normal: {estado}"
    yield


@pytest.fixture(scope="session")
def client():
    """Cliente HTTP apontado para a borda, compartilhado pela sessão."""
    with httpx.Client(base_url=BASE_URL, timeout=CLIENT_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def load_golden():
    """Lê um golden master gravado a partir de uma resposta real observada.

    Formato de expected/<nome>.json: {"request": {...}, "status": <int>, "body": {...}}
    """
    def _load(name: str) -> dict:
        path = EXPECTED_DIR / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return _load
