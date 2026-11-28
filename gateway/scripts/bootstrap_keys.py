"""Provisionamento idempotente das chaves virtuais do gateway (Passo 12, ADRs 0008 e 0010).

Roda como serviço `gateway-bootstrap` do compose a cada `docker compose up`, depois que o
gateway fica saudável, e termina. A app só sobe se ele terminar com código 0.

Estado desejado (Configuration as Code): a lista IDENTITIES abaixo. Para cada identidade:

1. consulta a chave no gateway (`GET /key/info`, autenticado com a master key);
2. não existe  -> cria com o valor fixo vindo do ambiente (`POST /key/generate`, campo `key`);
3. existe      -> compara só os campos de POLÍTICA; se divergem, alinha (`POST /key/update`);
4. relê a chave e confere que a política efetiva é a desejada.

Nunca recria uma chave existente, nunca mexe em `spend` e nunca apaga histórico: provisionar
de novo não é resetar o estado operacional. O reset de gasto existe só para as chaves de
demonstração, em comando separado e explícito:

    docker compose run --rm gateway-bootstrap --reset-spend governance-budget-demo

Credenciais nunca vão para o log: aparecem só pelo alias e pelos 4 últimos caracteres.
Só biblioteca padrão.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:4000").rstrip("/")
MASTER_KEY = os.environ["GATEWAY_MASTER_KEY"]

CAPABILITIES = ["ticket-classification", "order-extraction", "reply-suggestion", "topics-report"]

# Política de cada identidade (ADR 0010). `env` diz de onde vem o valor da chave.
# Valores em US$, a mesma unidade dos preços do provider-fake configurados no gateway.
IDENTITIES = [
    {
        "env": "HELPDESK_GATEWAY_KEY",
        "key_alias": "helpdesk-app",
        "models": CAPABILITIES,               # só as 4 capacidades; nunca os grupos internos
        "max_budget": 20.0,                   # hard limit do mês (política didática, ADR 0009)
        "soft_budget": 15.0,                  # aviso aos 75%: não bloqueia (sem canal de alerta local)
        "budget_duration": "30d",             # orçamento periódico: zera a cada 30 dias
        "rpm_limit": 600,                     # proteção contra laço descontrolado, não cota
        "metadata": {"purpose": "consumo normal do helpdesk", "owner": "time-helpdesk",
                     "cost_center": "atendimento", "environment": "local"},
        "resettable": False,
    },
    {
        "env": "GOVERNANCE_BUDGET_KEY",
        "key_alias": "governance-budget-demo",
        "models": ["ticket-classification"],
        "max_budget": 0.0004,                 # 3 chamadas da F1 (US$ 0,0001575 cada) e a 4ª recusa
        "soft_budget": None,
        "budget_duration": None,              # acumulado: só o reset explícito zera
        "rpm_limit": None,                    # isola a causa da recusa: só orçamento
        "metadata": {"purpose": "demonstração de recusa por orçamento", "owner": "arquitetura",
                     "environment": "local"},
        "resettable": True,
    },
    {
        "env": "GOVERNANCE_RATE_KEY",
        "key_alias": "governance-rate-demo",
        "models": ["ticket-classification"],
        "max_budget": 1.0,                    # ~6.300 chamadas da F1: nunca recusa por dinheiro
        "soft_budget": None,
        "budget_duration": None,
        "rpm_limit": 3,                       # 3 requisições por janela de 60 s; a 4ª recusa
        "metadata": {"purpose": "demonstração de recusa por limite de requisições",
                     "owner": "arquitetura", "environment": "local"},
        "resettable": True,
    },
]
POLICY_FIELDS = ["key_alias", "models", "max_budget", "soft_budget", "budget_duration",
                 "rpm_limit", "metadata"]


class BootstrapError(Exception):
    pass


def mask(key: str) -> str:
    return f"sk-...{key[-4:]}"


def call(method: str, path: str, body: dict | None = None, timeout: float = 15.0):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{GATEWAY_URL}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read() or b"{}")
        except ValueError:
            payload = {}
        return error.code, payload


def wait_ready(limit: float = 90.0) -> None:
    """Prontidão verificada, não espera fixa: gateway respondendo E banco conectado."""
    deadline = time.monotonic() + limit
    last = "sem resposta"
    while time.monotonic() < deadline:
        try:
            status, body = call("GET", "/health/readiness", timeout=5)
            if status == 200 and body.get("db") == "connected":
                return
            last = f"status={status} db={body.get('db')}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = type(error).__name__
        time.sleep(1)
    raise BootstrapError(f"gateway não ficou pronto em {limit:.0f} s ({last})")


def desired(identity: dict) -> dict:
    return {field: identity[field] for field in POLICY_FIELDS}


def current(info: dict) -> dict:
    have = {field: info.get(field) for field in POLICY_FIELDS}
    # O LiteLLM guarda o soft_budget da chave numa linha própria de orçamento, não na chave.
    have["soft_budget"] = (info.get("litellm_budget_table") or {}).get("soft_budget")
    return have


def diff(want: dict, have: dict) -> list[str]:
    changed = []
    for field, value in want.items():
        other = have.get(field)
        if field == "models":
            if sorted(value or []) != sorted(other or []):
                changed.append(field)
        elif field == "metadata":
            # O gateway pode acrescentar chaves próprias ao metadata: compara só as nossas.
            if any((other or {}).get(k) != v for k, v in value.items()):
                changed.append(field)
        elif value != other:
            changed.append(field)
    return changed


def get_info(key: str) -> dict | None:
    status, body = call("GET", f"/key/info?key={key}")
    if status == 404:
        return None
    if status != 200:
        raise BootstrapError(f"/key/info respondeu {status}: {body.get('error', {}).get('type')}")
    return body["info"]


def reconcile(identity: dict) -> str:
    key = os.environ.get(identity["env"], "")
    if not key.startswith("sk-"):
        raise BootstrapError(f"{identity['env']} ausente ou sem o prefixo sk- exigido pelo gateway")
    want = desired(identity)
    info = get_info(key)
    if info is None:
        status, body = call("POST", "/key/generate", {"key": key, **want})
        if status != 200:
            raise BootstrapError(f"criar {identity['key_alias']}: {status} "
                                 f"{body.get('error', {}).get('message', '')[:160]}")
        action = "criada"
    else:
        changed = diff(want, current(info))
        if changed:
            # Só campos de política: `spend` não é enviado, então o gasto acumulado fica.
            status, body = call("POST", "/key/update", {"key": key, **{f: want[f] for f in changed}})
            if status != 200:
                raise BootstrapError(f"atualizar {identity['key_alias']}: {status} "
                                     f"{body.get('error', {}).get('message', '')[:160]}")
            action = f"política alinhada ({', '.join(changed)})"
        else:
            action = "já conforme"
    # Verificação final: a política efetiva tem de ser a desejada.
    info = get_info(key)
    if info is None or diff(want, current(info)):
        raise BootstrapError(f"{identity['key_alias']}: política efetiva diverge da desejada")
    print(f"[bootstrap] {identity['key_alias']:<24} {mask(key)}  {action}; "
          f"budget={info.get('max_budget')} rpm={info.get('rpm_limit')} "
          f"spend={info.get('spend'):.7f}", flush=True)
    return action


# O gateway grava o gasto no banco em lote, a cada 10 s + 0 a 5 s de sorteio
# (PROXY_BATCH_WRITE_AT do LiteLLM v1.102.1). Um reset feito com gasto ainda na fila é
# desfeito quando o lote chega. Por isso o reset espera o gasto parar de mudar por um
# intervalo inteiro, zera, e confere depois de outro intervalo.
FLUSH_INTERVAL = 16.0


def wait_spend_stable(key: str, limit: float = 90.0) -> float:
    deadline = time.monotonic() + limit
    last, since = get_info(key)["spend"], time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(2)
        spend = get_info(key)["spend"]
        if spend != last:
            last, since = spend, time.monotonic()
        elif time.monotonic() - since >= FLUSH_INTERVAL:
            return spend
    raise BootstrapError(f"o gasto não estabilizou em {limit:.0f} s; há chamadas em andamento?")


def reset_spend(alias: str, attempts: int = 3) -> None:
    """Zera o gasto de UMA chave de demonstração. Nunca a do helpdesk.

    Use sem tráfego na chave: o reset é um procedimento de laboratório, não de produção.
    """
    identity = next((i for i in IDENTITIES if i["key_alias"] == alias), None)
    if identity is None or not identity["resettable"]:
        raise BootstrapError(f"reset de gasto só é permitido nas chaves de demonstração, não em {alias!r}")
    key = os.environ[identity["env"]]
    for attempt in range(1, attempts + 1):
        before = wait_spend_stable(key)
        status, body = call("POST", "/key/update", {"key": key, "spend": 0.0})
        if status != 200:
            raise BootstrapError(f"reset de {alias}: {status} {body.get('error', {}).get('message', '')[:160]}")
        time.sleep(FLUSH_INTERVAL)
        after = get_info(key)["spend"]
        print(f"[bootstrap] {alias} {mask(key)} tentativa {attempt}: spend {before:.7f} -> {after:.7f}",
              flush=True)
        if after == 0:
            print(f"[bootstrap] {alias} gasto zerado e confirmado após um ciclo de gravação", flush=True)
            return
    raise BootstrapError(f"{alias}: o gasto voltou depois do reset em {attempts} tentativas")


def main(argv: list[str]) -> int:
    try:
        wait_ready()
        if argv[:1] == ["--reset-spend"] and len(argv) == 2:
            reset_spend(argv[1])
            return 0
        if argv:
            raise BootstrapError("uso: bootstrap_keys.py [--reset-spend <alias de demonstração>]")
        for identity in IDENTITIES:
            reconcile(identity)
        print("[bootstrap] concluído", flush=True)
        return 0
    except (BootstrapError, KeyError, urllib.error.URLError) as error:
        print(f"[bootstrap] FALHA: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
