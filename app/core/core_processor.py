import json
import time
from dataclasses import dataclass
from logging import Logger

from app.config.aws_config import AwsConfig
from app.config.database_config import ConfigDatabase
from app.core.mapper.equity_snapshot import SnapshotAcao
from app.core.service.financial_analyzer_service import FinancialAnalyzerService
from app.core.service.persistencia_service import PersistenciaHistoricoService
from app.external.database.entity.insight_entity import InsightEntity
from app.external.database.insight_repository import InsightRepository


@dataclass
class CoreProcessor:
    logger: Logger
    historico_service: PersistenciaHistoricoService
    financial_analyzer: FinancialAnalyzerService
    insight_repository: InsightRepository
    aws: AwsConfig
    session_factory: object

    @staticmethod
    def instanciar(logger: Logger):
        persistence = PersistenciaHistoricoService()
        financial_analyzer = FinancialAnalyzerService(logger=logger)
        session_factory = ConfigDatabase().session
        insight_repository = InsightRepository(logger=logger)
        aws = AwsConfig()
        return CoreProcessor(logger=logger,
                             historico_service=persistence,
                             financial_analyzer=financial_analyzer,
                             insight_repository=insight_repository,
                             aws=aws,
                             session_factory=session_factory)

    def ensure_queue(self, queue_name: str) -> str:
        try:
            response = self.aws.get_sqs_client().get_queue_url(QueueName=queue_name)
            return response['QueueUrl']
        except Exception as e:
            self.logger.info(f"Fila {queue_name} não encontrada. Tentando criar...")
            try:
                response = self.aws.get_sqs_client().create_queue(QueueName=queue_name)
                return response['QueueUrl']
            except Exception as create_err:
                self.logger.critical(f"Erro fatal ao criar fila {queue_name}: {create_err}")
                raise create_err

    def consume_messages(self, queue_url: str):
        while True:
            try:
                resp = self.aws.get_sqs_client().receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=10
                )
                messages = resp.get('Messages', [])

                if not messages:
                    self.logger.info("Nenhuma mensagem na fila; aguardando...")
                    continue

                for m in messages:
                    receipt_handle = m['ReceiptHandle']
                    try:
                        ativo = json.loads(m['Body'])
                        
                        with self.session_factory() as session:
                            try:
                                self.processar_persistencia(session, ativo)
                                insight_dict = self.financial_analyzer.gerar_insight_fundamentalista(ativo)
                                self.salvar_insight(session, insight_dict)
                                session.commit()
                            except Exception as e:
                                session.rollback()
                                raise e
                        
                        self.aws.get_sqs_client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                        self.logger.info("Mensagem processada e deletada com sucesso")

                    except (json.JSONDecodeError, ValueError, TypeError) as bad_data_err:

                        self.logger.error(f"Payload inválido. Descartando mensagem: {bad_data_err}")
                        self.aws.get_sqs_client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

                    except Exception as process_err:
                        self.logger.error(f"Erro ao processar ativo. Mantendo na fila para retry: {process_err}",
                                          exc_info=True)

            except Exception as loop_err:
                self.logger.error(f"Erro crítico no loop SQS: {loop_err}")
                time.sleep(5)

    def processar_persistencia(self, session, ativo):
        snapshot = SnapshotAcao(ativo)
        self.logger.info(f"Iniciando persistencia do objeto: {snapshot}")
        self.historico_service.registrar_snapshot(session, snapshot)

    def salvar_insight(self, session, insight_dict):
        entidade: InsightEntity = InsightEntity(
            simbolo=insight_dict["simbolo"],
            preco_justo_graham=insight_dict["preco_justo_graham"],
            margem_seguranca_percent=insight_dict["margem_seguranca_percent"],
            recomendacao=insight_dict["recomendacao"],
            detalhes_json=insight_dict["detalhes_json"]
        )
        self.insight_repository.salvar(session, entidade)
