"""Sondas do Passo 10: cada feature pela borda, com um modo de falha ligado no provider.

Para cada cenário: reseta o provider, liga o modo no modelo físico da feature, chama a
borda como um cliente real, espera um pouco e lê /admin/calls. Mede status, tempo,
tentativas, intervalos entre tentativas, tokens e chamadas ainda abertas. No fim o
provider volta ao modo normal, mesmo com erro. Só biblioteca padrão.

Uso (na raiz do repositório, com o compose no ar):

    python docs/resiliencia/sondas_resiliencia.py MODO [F1 F2 F3 F4] [--espera 8] [--saida arquivo.json]

MODO: normal | error_500 | error_429 | slow | timeout

Em `timeout` e `slow` sem política, chamadas continuam vivas depois da resposta. Reinicie
`gateway` e `app` entre experimentos: docker compose restart gateway app
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime

EDGE = "http://localhost:8000"
PROVIDER = "http://localhost:8090"

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"

# O modelo físico aparece aqui, e não na app, só para a sonda saber onde injetar a falha.
FEATURES = {
    "F1": ("/tickets/classification", {"ticket_id": "TK-00042", "text": T42}, "openai", "gpt-fake-large"),
    "F2": ("/tickets/reply-suggestion", {"ticket_id": "TK-00042", "text": T42}, "anthropic", "claude-fake-large"),
    "F3": ("/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}, "anthropic", "claude-fake-large"),
    "F4": ("/tickets/extraction", {"ticket_id": "TK-00200", "text": T200}, "openai", "gpt-fake-large"),
}
PRECOS = {"gpt-fake-large": (2.50, 10.00), "claude-fake-large": (3.00, 15.00)}


def http(method: str, url: str, body: dict | None = None, timeout: float = 60):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resposta:
            status, bruto = resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        status, bruto = erro.code, erro.read()
    segundos = round(time.monotonic() - inicio, 3)
    try:
        return status, json.loads(bruto), segundos
    except ValueError:
        return status, bruto.decode("utf-8", "replace"), segundos


def intervalos(chamadas: list[dict]) -> list[float]:
    """Pausa entre o fim de uma tentativa e o início da seguinte (s)."""
    pausas = []
    for anterior, seguinte in zip(chamadas, chamadas[1:]):
        inicio_anterior = datetime.fromisoformat(anterior["ts"])
        delta = (datetime.fromisoformat(seguinte["ts"]) - inicio_anterior).total_seconds()
        if anterior["duration_ms"] is not None and anterior["duration_ms"] / 1000 <= delta:
            delta -= anterior["duration_ms"] / 1000
        pausas.append(round(delta, 3))
    return pausas


def cenario(modo: str, feature: str, espera: float) -> dict:
    rota, corpo, provider, modelo = FEATURES[feature]
    http("POST", f"{PROVIDER}/admin/reset")
    if modo != "normal":
        http("POST", f"{PROVIDER}/admin/failures", {"provider": provider, "model": modelo, "mode": modo})
    quando = datetime.now().astimezone().isoformat(timespec="seconds")
    status, resposta, segundos = http("POST", f"{EDGE}{rota}", corpo)
    time.sleep(espera)
    _, chamadas, _ = http("GET", f"{PROVIDER}/admin/calls?last=50")
    if isinstance(chamadas, dict):
        chamadas = chamadas.get("calls", [])
    chamadas = sorted(chamadas, key=lambda c: c["ts"])
    entrada = sum(c["input_tokens"] or 0 for c in chamadas)
    saida = sum(c["output_tokens"] or 0 for c in chamadas)
    preco_in, preco_out = PRECOS[modelo]
    return {
        "modo": modo,
        "feature": feature,
        "quando": quando,
        "provider": provider,
        "modelo": modelo,
        "status": status,
        "segundos": segundos,
        "resposta": str(resposta)[:300],
        "tentativas": len(chamadas),
        "intervalos_s": intervalos(chamadas),
        "abertas_apos_espera": sum(1 for c in chamadas if c["duration_ms"] is None),
        "espera_s": espera,
        "tokens_entrada": entrada,
        "tokens_saida": saida,
        "custo_usd_saidas_concluidas": round((entrada * preco_in + saida * preco_out) / 1_000_000, 6),
        "chamadas": [
            {k: c[k] for k in ("ts", "model", "status", "input_tokens", "output_tokens", "duration_ms")}
            for c in chamadas
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("modo", choices=["normal", "error_500", "error_429", "slow", "timeout"])
    parser.add_argument("features", nargs="*", default=["F1", "F4", "F2", "F3"])
    parser.add_argument("--espera", type=float, default=2.0)
    parser.add_argument("--saida")
    args = parser.parse_args()
    resultados = []
    try:
        for feature in args.features:
            resultado = cenario(args.modo, feature, args.espera)
            resultados.append(resultado)
            print(
                f"{args.modo:10} {feature}  HTTP {resultado['status']}  {resultado['segundos']:7.3f}s  "
                f"tentativas={resultado['tentativas']} abertas={resultado['abertas_apos_espera']} "
                f"intervalos={resultado['intervalos_s']}",
                flush=True,
            )
    finally:
        # O reset apaga o registro, por isso só acontece depois de lido.
        http("POST", f"{PROVIDER}/admin/reset")
        if args.saida:
            with open(args.saida, "w", encoding="utf-8") as arquivo:
                json.dump(resultados, arquivo, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
