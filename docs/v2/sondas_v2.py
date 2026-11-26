"""Sondas do Passo 09: as quatro features observadas pela borda.

Chama o helpdesk pela borda (edge, porta 8000), como um cliente real, e lê o registro do
provider-fake (/admin/calls) para saber qual provider, modelo físico e tarefa atenderam.
Imprime JSON. Só biblioteca padrão. Generaliza docs/piloto/sondas.py (que fica como está).

Uso (na raiz do repositório, com o compose no ar):

    docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
      -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
      -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
      python:3.12-slim python docs/v2/sondas_v2.py FASE [FEATURE]

Fases:
  features        uma chamada de cada feature (F1, F4, F2, F3 com 2026-08-01) e quem atendeu
  falha FEATURE   a feature com o modelo físico dela em error_500: status, tempo e tentativas
  contar          quantas chamadas o provider registrou desde o último /admin/reset (não reseta)

Atenção: "features" e "falha" começam com POST /admin/reset (limpa o registro e volta o
provider ao modo normal). "falha" liga um modo de falha e o desliga no fim, mesmo com erro.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

EDGE = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"

# Feature -> (rota, payload, provider e modelo físico configurados hoje no gateway para ela).
# O modelo físico aparece aqui, e não na app, só para a sonda saber qual falha injetar.
FEATURES = {
    "F1": ("/tickets/classification", {"ticket_id": "TK-00042", "text": T42}, "openai", "gpt-fake-large"),
    "F4": ("/tickets/extraction", {"ticket_id": "TK-00200", "text": T200}, "openai", "gpt-fake-large"),
    "F2": ("/tickets/reply-suggestion", {"ticket_id": "TK-00042", "text": T42}, "anthropic", "claude-fake-large"),
    "F3": ("/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}, "anthropic", "claude-fake-large"),
}


def http(method: str, url: str, body: dict | None = None, timeout: float = 120):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    elapsed = round(time.monotonic() - t0, 3)
    try:
        return status, json.loads(raw), elapsed
    except ValueError:
        return status, raw.decode("utf-8", "replace"), elapsed


def reset() -> None:
    http("POST", f"{PROVIDER}/admin/reset")


def calls(last: int = 5000) -> list[dict]:
    _, body, _ = http("GET", f"{PROVIDER}/admin/calls?last={last}")
    registros = body if isinstance(body, list) else body.get("calls", body)
    campos = ("ts", "provider", "model", "task", "stream", "status", "duration_ms")
    return [{k: c.get(k) for k in campos} for c in registros]


def resumo(feature: str, resposta):
    if feature in ("F2", "F3") and isinstance(resposta, dict):
        return {k: (v if k not in ("suggestion", "topics") else f"<{len(json.dumps(v, ensure_ascii=False))} caracteres>")
                for k, v in resposta.items()}
    return resposta


def fase_features() -> dict:
    reset()
    saida = []
    for feature, (rota, payload, _, _) in FEATURES.items():
        antes = len(calls())
        status, corpo, seg = http("POST", f"{EDGE}{rota}", payload)
        depois = calls()  # do mais recente para o mais antigo
        novos = list(reversed(depois[: len(depois) - antes]))
        saida.append({"feature": feature, "rota": rota, "status": status, "segundos": seg,
                      "resposta": resumo(feature, corpo),
                      "atendido_por": [{k: c[k] for k in ("provider", "model", "task", "stream")} for c in novos]})
    return {"features": saida}


def fase_falha(feature: str) -> dict:
    rota, payload, provider, modelo = FEATURES[feature]
    reset()
    http("POST", f"{PROVIDER}/admin/failures", {"provider": provider, "model": modelo, "mode": "error_500"})
    try:
        status, corpo, seg = http("POST", f"{EDGE}{rota}", payload)
        registro = calls()
    finally:
        reset()
    return {"feature": feature, "falha_injetada": f"{provider}/{modelo} error_500", "status": status,
            "segundos": seg, "resposta": resumo(feature, corpo),
            "tentativas_no_provider": len(registro), "admin_calls": registro}


def fase_contar() -> dict:
    registro = calls()
    por_tarefa: dict[str, int] = {}
    for c in registro:
        chave = f"{c['provider']}/{c['model']}/{c['task']}"
        por_tarefa[chave] = por_tarefa.get(chave, 0) + 1
    return {"chamadas_no_provider": len(registro), "por_provider_modelo_tarefa": por_tarefa}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["features"]:
        print(json.dumps(fase_features(), ensure_ascii=False, indent=2))
    elif len(args) == 2 and args[0] == "falha" and args[1].upper() in FEATURES:
        print(json.dumps(fase_falha(args[1].upper()), ensure_ascii=False, indent=2))
    elif args == ["contar"]:
        print(json.dumps(fase_contar(), ensure_ascii=False, indent=2))
    else:
        print("uso: sondas_v2.py features | falha F1|F2|F3|F4 | contar", file=sys.stderr)
        sys.exit(2)
