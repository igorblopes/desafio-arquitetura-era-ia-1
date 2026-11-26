"""Sondas do Passo 08: o piloto da F1 observado pela borda.

Chama o helpdesk pela borda (edge, porta 8000), como um cliente real, e lê o registro
do provider-fake (/admin/calls) para saber qual provider e qual modelo físico atenderam.
Imprime JSON. Usa só a biblioteca padrão, para rodar em qualquer python:3.12-slim.

Uso (na raiz do repositório, com o compose no ar):

    docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
      -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
      -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
      python:3.12-slim python docs/piloto/sondas.py FASE

Fases:
  f1        uma classificação (TK-00042) e o registro do provider
  f1-falha  a mesma classificação com o gpt-fake-large em error_500 (conta as tentativas)
  features  uma chamada de cada feature (F1, F4, F2, F3) e quem atendeu cada uma

Atenção: toda fase começa com POST /admin/reset (limpa o registro e volta o provider ao
modo normal). A fase f1-falha liga um modo de falha e o desliga no fim.
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

# Mesmas entradas da caracterização (Passo 04).
T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"


def http(method: str, url: str, body: dict | None = None, timeout: float = 120):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
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


def calls(last: int = 20) -> list[dict]:
    _, body, _ = http("GET", f"{PROVIDER}/admin/calls?last={last}")
    registros = body if isinstance(body, list) else body.get("calls", body)
    campos = ("ts", "provider", "model", "task", "stream", "status", "duration_ms")
    return [{k: c.get(k) for k in campos} for c in registros]


def chamada(rota: str, payload: dict) -> dict:
    status, body, elapsed = http("POST", f"{EDGE}{rota}", payload)
    return {"rota": rota, "status": status, "segundos": elapsed, "resposta": body}


def fase_f1() -> dict:
    reset()
    r = chamada("/tickets/classification", {"ticket_id": "TK-00042", "text": T42})
    return {"f1": r, "admin_calls": calls()}


def fase_f1_falha() -> dict:
    reset()
    http("POST", f"{PROVIDER}/admin/failures",
         {"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"})
    try:
        r = chamada("/tickets/classification", {"ticket_id": "TK-00042", "text": T42})
        registro = calls()
    finally:
        reset()
    return {"f1": r, "tentativas_no_provider": len(registro), "admin_calls": registro}


def fase_features() -> dict:
    reset()
    passos = [
        ("F1", "/tickets/classification", {"ticket_id": "TK-00042", "text": T42}),
        ("F4", "/tickets/extraction", {"ticket_id": "TK-00200", "text": T200}),
        ("F2", "/tickets/reply-suggestion", {"ticket_id": "TK-00042", "text": T42}),
        ("F3", "/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}),
    ]
    resultado = []
    for feature, rota, payload in passos:
        antes = len(calls(200))
        r = chamada(rota, payload)
        depois = calls(200)  # do mais recente para o mais antigo
        novos = depois[: len(depois) - antes]
        resposta = r["resposta"]
        if feature in ("F2", "F3") and isinstance(resposta, dict):
            # Texto longo: registra o tamanho, não o conteúdo inteiro.
            resposta = {k: (v if k not in ("suggestion", "topics") else f"<{len(json.dumps(v, ensure_ascii=False))} caracteres>")
                        for k, v in resposta.items()}
        resultado.append({"feature": feature, "rota": rota, "status": r["status"],
                          "segundos": r["segundos"], "resposta": resposta,
                          "atendido_por": [{"provider": c["provider"], "model": c["model"], "task": c["task"]}
                                           for c in novos]})
    return {"features": resultado}


FASES = {"f1": fase_f1, "f1-falha": fase_f1_falha, "features": fase_features}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in FASES:
        print(f"uso: sondas.py {{{'|'.join(FASES)}}}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(FASES[sys.argv[1]](), ensure_ascii=False, indent=2))
