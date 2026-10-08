"""Observabilidade HTTP do worker.

O compose da infra já expõe a porta 8080 para scrape. Este módulo mantém um
servidor simples com `/health` e `/metrics`; quando `prometheus_client` está
instalado, os contadores são exportados no formato Prometheus. Nos testes locais
sem a dependência, os métodos viram no-op e o restante da aplicação continua
funcionando.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging import Logger
from time import perf_counter
from typing import Callable

try:  # pragma: no cover - exercitado quando a imagem instala requirements.txt
    from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
    from prometheus_client.exposition import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover - caminho local sem dependencia instalada
    CollectorRegistry = Counter = Histogram = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest(_registry=None) -> bytes:  # type: ignore[no-redef]
        return b""


class ObservabilityMetrics:
    """Métricas de baixo nível do worker SQS."""

    def __init__(self):
        self.habilitado = CollectorRegistry is not None
        self.registry = CollectorRegistry() if self.habilitado else None
        if not self.habilitado:
            return
        self.mensagens = Counter(
            "gerar_insights_mensagens_total",
            "Mensagens SQS observadas por fila e resultado.",
            ("fila", "resultado"),
            registry=self.registry,
        )
        self.latencia = Histogram(
            "gerar_insights_processamento_segundos",
            "Tempo de processamento de uma mensagem SQS.",
            ("fila",),
            registry=self.registry,
        )
        self.recomendacoes = Counter(
            "gerar_insights_recomendacoes_total",
            "Insights gravados por sinal quantitativo.",
            ("sinal",),
            registry=self.registry,
        )

    def registrar_mensagem(self, fila: str, resultado: str) -> None:
        if self.habilitado:
            self.mensagens.labels(fila=fila, resultado=resultado).inc()

    def registrar_recomendacao(self, recomendacao: str | None) -> None:
        if self.habilitado:
            self.recomendacoes.labels(sinal=recomendacao or "SEM_DADOS").inc()

    def observar_latencia(self, fila: str) -> Callable[[], None]:
        inicio = perf_counter()

        def concluir() -> None:
            if self.habilitado:
                self.latencia.labels(fila=fila).observe(perf_counter() - inicio)

        return concluir

    def payload_prometheus(self) -> bytes:
        return generate_latest(self.registry)


def iniciar_servidor_observabilidade(
    porta: int,
    logger: Logger,
    metricas: ObservabilityMetrics,
    habilitado: bool = True,
) -> ThreadingHTTPServer | None:
    if not habilitado:
        logger.info("Servidor de observabilidade desativado")
        return None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - API do BaseHTTPRequestHandler
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok\n")
                return
            if self.path == "/metrics":
                corpo = metricas.payload_prometheus()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.end_headers()
                self.wfile.write(corpo)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, formato, *args):
            logger.debug("observability: " + formato, *args)

    servidor = ThreadingHTTPServer(("", porta), Handler)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    logger.info("Servidor de observabilidade iniciado na porta %d", porta)
    return servidor
