"""Infraestrutura dos testes de governança (Passo 12, ADR 0010).

Integração real: gateway LiteLLM (4000) com o Postgres de governança, provider-fake (8090)
e, quando o teste diz, a borda (8000). A prova de bloqueio é sempre /admin/calls antes e
depois da requisição recusada, sem reset no meio; nada de mock.

Estado conhecido sem depender de execução anterior: cada teste que precisa esgotar orçamento
ou RPM cria a SUA chave virtual efêmera (valor aleatório, alias `test-governance-*`) com a
master key e a apaga no fim. Assim as chaves de demonstração do README e a chave do helpdesk
nunca são consumidas nem resetadas pelos testes, e uma chave nova começa com gasto zero e
janela de RPM vazia. A master key aqui faz o papel do provisionamento, como no bootstrap.

O provider é estado global: a suíte roda em sequência e cada teste começa e termina com
POST /admin/reset (que só zera o provider, nunca orçamento ou contadores do gateway).
"""

import os
import pathlib
import time
import uuid

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
PROVIDER_URL = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")
BASE_URL = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")


def _dotenv() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        path = ROOT / ".env.example"
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


ENV = {**_dotenv(), **os.environ}
MASTER_KEY = ENV["GATEWAY_MASTER_KEY"]
HELPDESK_KEY = ENV["HELPDESK_GATEWAY_KEY"]

GPT_L, CLA_L, GPT_M, CLA_M = "gpt-fake-large", "claude-fake-large", "gpt-fake-mini", "claude-fake-mini"
PROVIDER_OF = {GPT_L: "openai", GPT_M: "openai", CLA_L: "anthropic", CLA_M: "anthropic"}
PRICES = {GPT_L: (2.50, 10.00), CLA_L: (3.00, 15.00), GPT_M: (0.15, 0.60), CLA_M: (0.80, 4.00)}
T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
F1 = "ticket-classification"
# Custo de uma F1 com o T42 no gpt-fake-large: 19 tokens de entrada e 11 de saída.
F1_COST = (19 * 2.50 + 11 * 10.00) / 1_000_000          # US$ 0,0001575
FLUSH_LIMIT = 30.0  # o gasto vai ao banco em lote a cada 10 s + até 5 s (LiteLLM v1.102.1)


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES[model]
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


class Governance:
    def __init__(self) -> None:
        self.gateway = httpx.Client(base_url=GATEWAY_URL, timeout=httpx.Timeout(45.0, connect=5.0))
        self.provider = httpx.Client(base_url=PROVIDER_URL, timeout=10.0)
        self.edge = httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(45.0, connect=5.0))
        self._created: list[str] = []

    # ---- provider-fake
    def reset_provider(self) -> None:
        self.provider.post("/admin/reset").raise_for_status()

    def fail(self, model: str | None, mode: str, provider: str | None = None) -> None:
        body = {"provider": provider or PROVIDER_OF[model], "mode": mode}
        if model is not None:
            body["model"] = model
        self.provider.post("/admin/failures", json=body).raise_for_status()

    def calls(self) -> list[dict]:
        body = self.provider.get("/admin/calls", params={"last": 500}).json()
        body = body["calls"] if isinstance(body, dict) else body
        return sorted(body, key=lambda c: c["ts"])

    def count(self) -> int:
        return len(self.calls())

    # ---- gateway
    def chat(self, key: str | None, capability: str = F1, text: str = T42) -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
        return self.gateway.post("/v1/chat/completions", headers=headers, json={
            "model": capability, "messages": [{"role": "user", "content": f"TASK: classify\n{text}"}]})

    def refused_without_provider_call(self, key: str | None, capability: str = F1) -> httpx.Response:
        """Prova de bloqueio: conta /admin/calls, chama, espera, conta de novo."""
        before = self.count()
        response = self.chat(key, capability)
        time.sleep(0.5)
        assert response.status_code != 200, response.text
        assert self.count() == before, "a requisição recusada chegou ao provider"
        return response

    def new_key(self, models: list[str] | None = None, **policy) -> str:
        key = f"sk-test-governance-{uuid.uuid4().hex[:12]}"
        response = self.gateway.post("/key/generate", headers=self._admin(), json={
            "key": key, "key_alias": f"test-governance-{key[-12:]}",
            "models": models or [F1], **policy})
        assert response.status_code == 200, response.text
        self._created.append(key)
        return key

    def delete_key(self, key: str) -> None:
        self.gateway.post("/key/delete", headers=self._admin(), json={"keys": [key]})

    def key_info(self, key: str) -> dict:
        response = self.gateway.get("/key/info", params={"key": key}, headers=self._admin())
        response.raise_for_status()
        return response.json()["info"]

    def wait_spend(self, key: str, minimum: float) -> float:
        """Espera limitada até o gasto gravado no banco alcançar `minimum`."""
        deadline = time.monotonic() + FLUSH_LIMIT
        spend = self.key_info(key)["spend"]
        while spend < minimum - 1e-12 and time.monotonic() < deadline:
            time.sleep(1)
            spend = self.key_info(key)["spend"]
        return spend

    def exhaust_budget(self, key: str, limit: int = 6) -> int:
        """Chama a F1 até o orçamento esgotar (no máximo `limit`); devolve quantas passaram.

        Pausa curta entre chamadas: o LiteLLM reserva o custo máximo da requisição e libera a
        reserva logo DEPOIS da resposta; uma chamada colada na anterior pode ver a reserva
        ainda presa e ser recusada cedo (evidência 12). Recusa só conta como esgotamento se
        persistir depois da pausa.
        """
        allowed = 0
        for _ in range(limit):
            time.sleep(0.5)
            if self.chat(key).status_code == 200:
                allowed += 1
                continue
            time.sleep(1.0)
            if self.chat(key).status_code == 200:
                allowed += 1
                continue
            return allowed
        raise AssertionError(f"o orçamento não esgotou em {limit} chamadas")

    def exhaust_rpm(self, key: str, rpm: int) -> None:
        for _ in range(rpm):
            assert self.chat(key).status_code == 200

    def cleanup(self) -> None:
        for key in self._created:
            self.delete_key(key)
        self._created.clear()

    @staticmethod
    def _admin() -> dict:
        return {"Authorization": f"Bearer {MASTER_KEY}"}


def error_type(response: httpx.Response) -> str | None:
    return response.json().get("error", {}).get("type")


@pytest.fixture(scope="session")
def _governance() -> Governance:
    gov = Governance()
    try:
        ready = gov.gateway.get("/health/readiness").json()
        gov.reset_provider()
    except httpx.HTTPError as error:
        pytest.exit(f"Suba o ambiente antes (docker compose up -d --wait): {error}", returncode=2)
    if ready.get("db") != "connected":
        pytest.exit(f"gateway sem banco de governança: {ready}", returncode=2)
    return gov


@pytest.fixture
def gov(_governance: Governance):
    _governance.reset_provider()
    yield _governance
    _governance.reset_provider()
    _governance.cleanup()
