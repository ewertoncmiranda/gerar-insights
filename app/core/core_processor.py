import json
import hashlib
import time
from dataclasses import dataclass
from logging import Logger

from app.config.aws_config import AwsConfig
from app.config.database_config import ConfigDatabase
from app.core.mapper.equity_snapshot import SnapshotAcao
from app.core.service.financial_analyzer_service import FinancialAnalyzerService
from app.core.service.persistencia_service import PersistenciaHistoricoService
from app.core.service.serie_historica_service import SerieHistoricaService
from app.external.database.entity.insight_entity import InsightEntity
from app.external.database.insight_repository import InsightRepository


@dataclass
class CoreProcessor:
    logger: Logger
    historico_service: PersistenciaHistoricoService
    serie_historica_service: SerieHistoricaService
    financial_analyzer: FinancialAnalyzerService
    insight_repository: InsightRepository
    aws: AwsConfig
    session_factory: object

    @staticmethod
    def instanciar(logger: Logger):
        persistence = PersistenciaHistoricoService()
        serie_historica_service = SerieHistoricaService()
        financial_analyzer = FinancialAnalyzerService(logger=logger)
        session_factory = ConfigDatabase().session
        insight_repository = InsightRepository(logger=logger)
        aws = AwsConfig()
        return CoreProcessor(
            logger=logger,
            historico_service=persistence,
            serie_historica_service=serie_historica_service,
            financial_analyzer=financial_analyzer,
            insight_repository=insight_repository,
            aws=aws,
            session_factory=session_factory,
        )

    def ensure_queue(self, queue_name: str) -> str:
        try:
            response = self.aws.get_sqs_client().get_queue_url(QueueName=queue_name)
            return response["QueueUrl"]
        except Exception:
            self.logger.info(f"Fila {queue_name} nao encontrada. Tentando criar...")
            try:
                response = self.aws.get_sqs_client().create_queue(QueueName=queue_name)
                return response["QueueUrl"]
            except Exception as create_err:
                self.logger.critical(f"Erro fatal ao criar fila {queue_name}: {create_err}")
                raise create_err

    def consume_messages(self, queue_url: str):
        self.consume_queues({
            "ativos": (queue_url, self.processar_mensagem_ativo),
        })

    def consume_queues(self, queue_handlers: dict):
        while True:
            houve_mensagem = False
            for nome_fila, (queue_url, handler) in queue_handlers.items():
                houve_mensagem = self._consumir_fila(nome_fila, queue_url, handler) or houve_mensagem

            if not houve_mensagem:
                self.logger.info("Nenhuma mensagem nas filas; aguardando...")
                time.sleep(5)

    def _consumir_fila(self, nome_fila: str, queue_url: str, handler):
        try:
            resp = self.aws.get_sqs_client().receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=2,
            )
            messages = resp.get("Messages", [])

            for message in messages:
                receipt_handle = message["ReceiptHandle"]
                try:
                    payload = json.loads(message["Body"])
                    if nome_fila == "ativos" and not payload.get("dedupKey"):
                        payload["dedupKey"] = self._chave_legada(payload)

                    with self.session_factory() as session:
                        try:
                            handler(session, payload)
                            session.commit()
                        except Exception as error:
                            session.rollback()
                            raise error

                    self.aws.get_sqs_client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                    self.logger.info(f"Mensagem da fila {nome_fila} processada e deletada com sucesso")

                except (json.JSONDecodeError, ValueError, TypeError) as bad_data_err:
                    self.logger.error(f"Payload invalido na fila {nome_fila}. Descartando mensagem: {bad_data_err}")
                    self.aws.get_sqs_client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

                except Exception as process_err:
                    self.logger.error(
                        f"Erro ao processar mensagem da fila {nome_fila}. Mantendo na fila para retry: {process_err}",
                        exc_info=True,
                    )

            return bool(messages)
        except Exception as loop_err:
            self.logger.error(f"Erro critico no loop SQS da fila {nome_fila}: {loop_err}")
            time.sleep(5)
            return False

    def processar_mensagem_ativo(self, session, ativo):
        self.processar_persistencia(session, ativo)
        insight_dict = self.financial_analyzer.gerar_insight_fundamentalista(session, ativo)
        self.salvar_insight(session, insight_dict)

    def processar_mensagem_serie_historica(self, session, payload):
        total_candles = self.serie_historica_service.registrar_payload(session, payload)
        self.logger.info(f"Serie historica processada com {total_candles} candles")

    def processar_persistencia(self, session, ativo):
        snapshot = SnapshotAcao(ativo)
        self.logger.info(f"Iniciando persistencia do objeto: {snapshot}")
        self.historico_service.registrar_snapshot(session, snapshot)

    def salvar_insight(self, session, insight_dict):
        entidade: InsightEntity = InsightEntity(
            dedup_key=insight_dict["dedup_key"],
            simbolo=insight_dict["simbolo"],
            preco_justo_graham=insight_dict["preco_justo_graham"],
            margem_seguranca_percent=insight_dict["margem_seguranca_percent"],
            recomendacao=insight_dict["recomendacao"],
            detalhes_json=insight_dict["detalhes_json"],
        )
        self.insight_repository.salvar(session, entidade)

    @staticmethod
    def _chave_legada(payload: dict) -> str:
        """Compatibilidade para mensagens anteriores ao schemaVersion 1.0."""
        canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
