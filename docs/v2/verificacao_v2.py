"""Verificação do arquiteto (Passo 09): as features migradas contra um gateway simulado.

Generaliza docs/piloto/verificacao_f1.py para as quatro features. A suíte de caracterização
não cobre o que este script cobre:

- erros de negócio que dependem da resposta do modelo (502 da F1 e da F4);
- o número de requisições ao gateway quando ele falha (o adapter não pode retentar);
- o formato exato do que sai da aplicação: caminho, chave própria do gateway, capacidade
  lógica no campo model, prompt idêntico ao da v1 e nenhum parâmetro a mais;
- a F2 devolvendo o texto do modelo sem nenhuma transformação;
- a F3 dividindo os tickets nos mesmos lotes, montando o mesmo conteúdo e agregando como a v1.

Funciona: sobe um servidor HTTP local que imita POST /v1/chat/completions do gateway, registra
cada requisição, carrega a app real (helpdesk.main) apontada para ele e chama as rotas com o
TestClient. Não usa Docker, gateway nem provider-fake. Não altera nada no repositório.

Uso (na raiz do repositório; FEATURES = as features já migradas, por exemplo F1 F4):

    docker run --rm -v "${PWD}:/w" -v "${PWD}/data:/data:ro" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
      python:3.12-slim sh -c "pip install -q -r app/requirements.txt httpx && \
      python docs/v2/verificacao_v2.py FEATURES"

Uma feature listada que ainda chame o provider diretamente aparece como FALHOU (0 requisições
ao gateway): é assim que o script detecta uma migração incompleta.
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
T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"
TICKETS_POR_LOTE = 150  # regra da v1 (config.TICKETS_PER_CALL); o oráculo abaixo não lê a app


class GatewaySimulado(BaseHTTPRequestHandler):
    """Responde como o gateway: formato Chat Completions, nome lógico no campo model."""

    respostas: list[tuple[int, str]] = []   # uma por requisição; a última se repete
    recebidas: list[dict] = []

    def do_POST(self):  # noqa: N802
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        GatewaySimulado.recebidas.append({"caminho": self.path,
                                          "authorization": self.headers.get("Authorization"),
                                          "corpo": corpo})
        i = min(len(GatewaySimulado.recebidas), len(GatewaySimulado.respostas)) - 1
        status, conteudo = GatewaySimulado.respostas[i]
        if status == 200:
            payload = {"id": "chatcmpl-verificacao", "object": "chat.completion", "created": 0,
                       "model": corpo.get("model"),
                       "choices": [{"index": 0, "finish_reason": "stop",
                                    "message": {"role": "assistant", "content": conteudo}}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        else:
            payload = {"error": {"message": "falha simulada", "type": "internal_server_error",
                                 "param": None, "code": str(status)}}
        dados = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


def requisicao_ok(req: dict, capacidade: str, prompt: str) -> dict:
    corpo = req.get("corpo", {})
    return {
        "caminho /v1/chat/completions": req.get("caminho") == "/v1/chat/completions",
        "chave do gateway": req.get("authorization") == f"Bearer {CHAVE}",
        "capacidade lógica": corpo.get("model") == capacidade,
        "prompt da v1": corpo.get("messages") == [{"role": "user", "content": prompt}],
        "sem parâmetros extras": set(corpo) == {"model", "messages"},
    }


def tickets_do_periodo(inicio: str, fim: str) -> list[dict]:
    """Oráculo independente da app: lê data/tickets.jsonl e filtra pela data de criação."""
    selecionados = []
    with open(ROOT / "data" / "tickets.jsonl", encoding="utf-8") as f:
        for linha in f:
            t = json.loads(linha)
            if inicio <= t["created_at"][:10] <= fim:
                selecionados.append(t)
    return selecionados


def main(features: list[str]) -> int:
    servidor = HTTPServer(("127.0.0.1", 0), GatewaySimulado)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta = servidor.server_address[1]
    # GATEWAY_* é o que a v2 lê. FAKE_* só existe para a app ainda importar nos estados
    # transitórios (enquanto config.py ler essas chaves); nenhuma chamada as usa aqui.
    os.environ.update({"GATEWAY_URL": f"http://127.0.0.1:{porta}", "GATEWAY_API_KEY": CHAVE,
                       "FAKE_OPENAI_KEY": "sk-nao-usada", "FAKE_ANTHROPIC_KEY": "sk-nao-usada"})
    sys.path.insert(0, str(ROOT / "app"))
    from fastapi.testclient import TestClient
    from helpdesk.main import app

    cliente = TestClient(app, raise_server_exceptions=False)
    resultados: list[dict] = []

    def cenario(feature, nome, rota, payload, respostas, status, corpo=None,
                requisicoes=1, capacidade=None, prompts=None):
        GatewaySimulado.respostas = respostas
        GatewaySimulado.recebidas = []
        r = cliente.post(rota, json=payload)
        rec = list(GatewaySimulado.recebidas)
        verificacoes = {"status": r.status_code == status,
                        "corpo": corpo is None or (r.headers.get("content-type", "").startswith("application/json")
                                                   and r.json() == corpo),
                        "requisições ao gateway": len(rec) == requisicoes}
        if prompts is not None:
            for n, (req, prompt) in enumerate(zip(rec, prompts), 1):
                for k, v in requisicao_ok(req, capacidade, prompt).items():
                    verificacoes[f"req {n}: {k}"] = v
        resultados.append({"feature": feature, "cenario": nome, "ok": all(verificacoes.values()),
                           "status": r.status_code, "requisicoes_ao_gateway": len(rec),
                           "falhas": [k for k, v in verificacoes.items() if not v],
                           "corpo": r.text[:300]})

    if "F1" in features:
        rota, cap, p = "/tickets/classification", "ticket-classification", f"TASK: classify\n{T42}"
        t = {"ticket_id": "TK-00042", "text": T42}
        cenario("F1", "sucesso", rota, t, [(200, '{"category": "delivery", "priority": "high"}')], 200,
                {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"},
                capacidade=cap, prompts=[p])
        cenario("F1", "categoria fora da lista vira 502", rota, t,
                [(200, '{"category": "shipping", "priority": "high"}')], 502,
                {"detail": "Classificação fora dos valores permitidos"})
        cenario("F1", "prioridade fora da lista vira 502", rota, t,
                [(200, '{"category": "delivery", "priority": "urgent"}')], 502,
                {"detail": "Classificação fora dos valores permitidos"})
        cenario("F1", "gateway em 500: 500 e 1 requisição", rota, t, [(500, "")], 500)

    if "F4" in features:
        rota, cap, p = "/tickets/extraction", "order-extraction", f"TASK: extract\n{T200}"
        t = {"ticket_id": "TK-00200", "text": T200}
        cenario("F4", "sucesso", rota, t,
                [(200, '{"order_number": "#481516", "product": "fone de ouvido bluetooth"}')], 200,
                {"ticket_id": "TK-00200", "order_number": "#481516", "product": "fone de ouvido bluetooth"},
                capacidade=cap, prompts=[p])
        cenario("F4", "campos nulos preservados", rota, t,
                [(200, '{"order_number": null, "product": null}')], 200,
                {"ticket_id": "TK-00200", "order_number": None, "product": None})
        cenario("F4", "pedido em formato inválido vira 502", rota, t,
                [(200, '{"order_number": "481516", "product": "fone"}')], 502,
                {"detail": "Número de pedido em formato inválido"})
        cenario("F4", "gateway em 500: 500 e 1 requisição", rota, t, [(500, "")], 500)

    if "F2" in features:
        rota, cap, p = "/tickets/reply-suggestion", "reply-suggestion", f"TASK: suggest\n{T42}"
        t = {"ticket_id": "TK-00042", "text": T42}
        texto = "Olá!\n\nSentimos muito pelo atraso do pedido #481516.  \nVamos verificar — ç, ã, é ✓\n"
        cenario("F2", "texto devolvido sem transformação", rota, t, [(200, texto)], 200,
                {"ticket_id": "TK-00042", "suggestion": texto}, capacidade=cap, prompts=[p])
        cenario("F2", "gateway em 500: 500 e 1 requisição", rota, t, [(500, "")], 500)

    if "F3" in features:
        rota, cap = "/reports/topics", "topics-report"
        inicio, fim = "2026-08-01", "2026-08-02"
        sel = tickets_do_periodo(inicio, fim)
        lotes = [sel[i:i + TICKETS_POR_LOTE] for i in range(0, len(sel), TICKETS_POR_LOTE)]
        prompts = ["TASK: topics\n" + "\n".join(f"[{t['id']}] {t['text']}" for t in lote) for lote in lotes]
        # Respostas por lote escolhidas para exercitar a agregação: tema repetido entre lotes
        # (soma e corte de exemplos em 3), empate de contagem (desempate pelo nome).
        respostas_modelo = [
            {"topics": [{"topic": "Pedido extraviado", "count": 5, "examples": ["A1", "A2"]},
                        {"topic": "Troca", "count": 3, "examples": ["A3"]}]},
            {"topics": [{"topic": "Pedido extraviado", "count": 2, "examples": ["B1", "B2"]},
                        {"topic": "Atraso", "count": 3, "examples": ["B3"]}]},
        ]
        # Oráculo: a agregação da v1 (report.py na v1-coupled), reescrita aqui de forma independente.
        totais: dict[str, dict] = {}
        for resp in respostas_modelo[:len(lotes)]:
            for item in resp["topics"]:
                atual = totais.setdefault(item["topic"], {"count": 0, "examples": []})
                atual["count"] += item["count"]
                atual["examples"] = (atual["examples"] + item["examples"])[:3]
        esperado_topicos = sorted(({"topic": k, **v} for k, v in totais.items()),
                                  key=lambda t: (-t["count"], t["topic"]))
        cenario("F3", f"{len(sel)} tickets em {len(lotes)} lotes: conteúdo e agregação", rota,
                {"start": inicio, "end": fim},
                [(200, json.dumps(r, ensure_ascii=False)) for r in respostas_modelo], 200,
                {"start": inicio, "end": fim, "total_tickets": len(sel), "topics": esperado_topicos},
                requisicoes=len(lotes), capacidade=cap, prompts=prompts)
        cenario("F3", "período sem tickets: nenhuma requisição", rota,
                {"start": "2026-09-01", "end": "2026-09-30"}, [(200, "{}")], 200,
                {"start": "2026-09-01", "end": "2026-09-30", "total_tickets": 0, "topics": []},
                requisicoes=0)
        cenario("F3", "gateway em 500 no 1º lote: 500 e 1 requisição", rota,
                {"start": inicio, "end": fim}, [(500, "")], 500)

    servidor.shutdown()
    print(json.dumps(resultados, ensure_ascii=False, indent=2))
    tudo_ok = bool(resultados) and all(r["ok"] for r in resultados)
    print(f"FEATURES: {' '.join(features)}  CENÁRIOS: {len(resultados)}  "
          f"RESULTADO: {'OK' if tudo_ok else 'FALHOU'}")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    pedidas = [a.upper() for a in sys.argv[1:]]
    if not pedidas or any(f not in {"F1", "F2", "F3", "F4"} for f in pedidas):
        print("uso: verificacao_v2.py F1 [F2] [F3] [F4]", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(pedidas))
