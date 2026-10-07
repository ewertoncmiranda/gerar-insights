import threading

import boto3
from botocore.config import Config

from app.config.settings import Settings


class AwsConfig:
    """Configuracao AWS do worker com UM cliente SQS por processo (ISS-09).

    O cliente do boto3 e thread-safe e caro de criar (carrega o modelo do
    servico, abre o pool de conexoes): antes era recriado a cada
    receive/delete. Agora nasce na primeira chamada e e reaproveitado por
    todas as instancias de AwsConfig do processo.
    """

    _cliente_sqs = None
    _trava = threading.Lock()

    def __init__(self):
        self.settings = Settings()
        self.config = Config(
            region_name=self.settings.aws_region,
            connect_timeout=5,
            read_timeout=30
        )

    def get_sqs_client(self):
        if AwsConfig._cliente_sqs is None:
            with AwsConfig._trava:
                if AwsConfig._cliente_sqs is None:
                    AwsConfig._cliente_sqs = boto3.client(
                        'sqs',
                        endpoint_url=self.settings.localstack_endpoint,
                        aws_access_key_id=self.settings.aws_access_key_id,
                        aws_secret_access_key=self.settings.aws_secret_access_key,
                        region_name=self.settings.aws_region,
                        config=self.config,
                    )
        return AwsConfig._cliente_sqs

    @classmethod
    def descartar_cliente(cls) -> None:
        """So para testes: forca um cliente novo na proxima chamada."""
        with cls._trava:
            cls._cliente_sqs = None
