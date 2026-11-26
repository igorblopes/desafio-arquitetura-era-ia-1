"""Verificação do arquiteto (Passo 08): a F1 e o adapter contra um gateway simulado.

Os testes de caracterização não cobrem dois comportamentos que o piloto precisa preservar:
o 502 quando o modelo devolve uma categoria fora da lista, e o número de tentativas quando
o modelo falha. Este script os verifica sem Docker e sem o provider-fake:

- sobe um servidor HTTP local que imita o endpoint do gateway (POST /v1/chat/completions)
  e registra cada requisição recebida (caminho, chave, corpo);
- carrega a app real (helpdesk.main) apontada para esse servidor;
- chama a rota da F1 com o TestClient do FastAPI em quatro cenários.

Não é um teste versionado da suíte: é uma verificação independente do código produzido
pelo agente. Não altera nada no repositório.

Uso (na raiz do repositório):

    docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
      sh -c "pip install -q -r app/requirements.txt httpx && python docs/piloto/verificacao_f1.py"
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAVE = "sk-gateway-verificacao"


class GatewaySimulado(BaseHTTPRequestHandler):
    """Responde como o gateway: formato Chat Completions, nome lógico no campo model."""

    resposta: tuple[int, str] = (200, "{}")
    recebidas: list[dict] = []

    def do_POST(self):  # noqa: N802 (nome exigido pelo http.server)
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        GatewaySimulado.recebidas.append({
            "caminho": self.path,
            "authorization": self.headers.get("Authorization"),
            "corpo": corpo,
        })
        status, conteudo = GatewaySimulado.resposta
        if status == 200:
            payload = {
                "id": "chatcmpl-verificacao", "object": "chat.completion", "created": 0,
                "model": corpo.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": conteudo}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        else:
            payload = {"error": {"message": "falha simulada", "type": "internal_server_error",
                                 "param": None, "code": str(status)}}
        dados = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):  # silencia o log padrão
        pass


def main() -> int:
    servidor = HTTPServer(("127.0.0.1", 0), GatewaySimulado)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta = servidor.server_address[1]

    # Ambiente mínimo para importar a app. As chaves FAKE_* só são lidas porque F2, F3 e F4
    # ainda usam llm.py (estado transitório); nenhuma chamada a elas acontece aqui.
    os.environ.update({
        "GATEWAY_URL": f"http://127.0.0.1:{porta}",
        "GATEWAY_API_KEY": CHAVE,
        "FAKE_OPENAI_KEY": "sk-nao-usada",
        "FAKE_ANTHROPIC_KEY": "sk-nao-usada",
    })
    sys.path.insert(0, str(ROOT / "app"))
    from fastapi.testclient import TestClient
    from helpdesk.main import app

    cliente = TestClient(app, raise_server_exceptions=False)
    ticket = {"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}
    resultados = []

    def cenario(nome, resposta, esperado_status, esperado_corpo=None, esperado_requisicoes=1):
        GatewaySimulado.resposta = resposta
        GatewaySimulado.recebidas = []
        r = cliente.post("/tickets/classification", json=ticket)
        recebidas = list(GatewaySimulado.recebidas)
        ok = (r.status_code == esperado_status
              and (esperado_corpo is None or r.json() == esperado_corpo)
              and len(recebidas) == esperado_requisicoes)
        resultados.append({
            "cenario": nome, "ok": ok,
            "status": r.status_code, "corpo": r.text,
            "requisicoes_ao_gateway": len(recebidas), "primeira_requisicao": recebidas[0] if recebidas else None,
        })

    cenario("sucesso", (200, '{"category": "delivery", "priority": "high"}'), 200,
            {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"})
    cenario("categoria fora da lista vira 502", (200, '{"category": "shipping", "priority": "high"}'), 502,
            {"detail": "Classificação fora dos valores permitidos"})
    cenario("prioridade fora da lista vira 502", (200, '{"category": "delivery", "priority": "urgent"}'), 502,
            {"detail": "Classificação fora dos valores permitidos"})
    cenario("gateway em 500: erro propagado, sem retentativa no cliente", (500, ""), 500)

    # O que o adapter precisa enviar ao gateway (cenário de sucesso).
    req = resultados[0]["primeira_requisicao"] or {}
    corpo = req.get("corpo", {})
    contrato = {
        "caminho é /v1/chat/completions": req.get("caminho") == "/v1/chat/completions",
        "autentica com a chave do gateway": req.get("authorization") == f"Bearer {CHAVE}",
        "pede a capacidade lógica": corpo.get("model") == "ticket-classification",
        "uma mensagem de usuário com o prompt da v1": corpo.get("messages") == [
            {"role": "user", "content": f"TASK: classify\n{ticket['text']}"}],
        "sem parâmetros extras": set(corpo) == {"model", "messages"},
    }

    servidor.shutdown()
    saida = {"cenarios": resultados, "requisicao_ao_gateway": contrato}
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    tudo_ok = all(r["ok"] for r in resultados) and all(contrato.values())
    print("RESULTADO:", "OK" if tudo_ok else "FALHOU")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
