"""Experimentos 06 (recuperação) e 07 (erros sem retry) do Passo 10. Só biblioteca padrão.

    python docs/resiliencia/experimentos_extra.py recuperacao
    python docs/resiliencia/experimentos_extra.py nao-repetiveis
"""

import json
import sys
import threading
import time

from sondas_resiliencia import EDGE, FEATURES, PROVIDER, http


def chamadas():
    _, corpo, _ = http("GET", f"{PROVIDER}/admin/calls?last=50")
    corpo = corpo["calls"] if isinstance(corpo, dict) else corpo
    return sorted(corpo, key=lambda c: c["ts"])


def recuperacao():
    """Liga a falha, dispara a requisição e volta ao normal assim que a 1ª tentativa chega."""
    saida = []
    for modo, feature in [("error_500", "F1"), ("error_429", "F4"), ("timeout", "F1"), ("error_500", "F2")]:
        rota, corpo, provider, modelo = FEATURES[feature]
        alvo = {"provider": provider, "model": modelo}
        http("POST", f"{PROVIDER}/admin/reset")
        http("POST", f"{PROVIDER}/admin/failures", {**alvo, "mode": modo})
        resultado = {}
        pedido = threading.Thread(target=lambda: resultado.update(r=http("POST", f"{EDGE}{rota}", corpo)))
        pedido.start()
        limite = time.monotonic() + 10
        while not chamadas() and time.monotonic() < limite:
            time.sleep(0.02)
        http("POST", f"{PROVIDER}/admin/failures", {**alvo, "mode": "normal"})  # sem apagar o registro
        pedido.join()
        status, _, segundos = resultado["r"]
        vistas = [c["status"] for c in chamadas()]
        saida.append({"falha": modo, "feature": feature, "status": status, "segundos": segundos,
                      "status_no_provider": vistas})
        print(f"{modo:10} {feature}  HTTP {status}  {segundos:6.3f}s  provider={vistas}")
    http("POST", f"{PROVIDER}/admin/reset")
    return saida


def nao_repetiveis():
    saida = []

    def rodar(nome, metodo, url, corpo, cabecalhos_extra=None):
        http("POST", f"{PROVIDER}/admin/reset")
        status, resposta, segundos = http(metodo, url, corpo)
        time.sleep(1)
        total = len(chamadas())
        saida.append({"cenario": nome, "status": status, "segundos": segundos,
                      "chamadas_no_provider": total, "resposta": str(resposta)[:200]})
        print(f"{nome:45} HTTP {status}  {segundos:6.3f}s  chamadas={total}")

    rodar("entrada inválida na API do helpdesk", "POST", f"{EDGE}/tickets/classification", {"ticket_id": "TK-1"})
    rodar("entrada maior que o contexto (400 do provider)", "POST", f"{EDGE}/tickets/classification",
          {"ticket_id": "TK-1", "text": "pedido atrasado " * 2500})
    http("POST", f"{PROVIDER}/admin/reset")
    return saida


if __name__ == "__main__":
    fase = sys.argv[1]
    dados = {"recuperacao": recuperacao, "nao-repetiveis": nao_repetiveis}[fase]()
    with open(f"docs/resiliencia/evidencias/{fase}.json", "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
