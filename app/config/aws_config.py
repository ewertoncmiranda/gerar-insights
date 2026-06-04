import boto3
from botocore.config import Config

from app.config.settings import Settings


class AwsConfig:

    def __init__(self):
        self.settings = Settings()
        self.config = Config(
            region_name=self.settings.aws_region,
            connect_timeout=5,
            read_timeout=30
        )

    def get_sqs_client(self):
        return boto3.client('sqs',
                            endpoint_url=self.settings.localstack_endpoint,
                            aws_access_key_id=self.settings.aws_access_key_id,
                            aws_secret_access_key=self.settings.aws_secret_access_key,
                            region_name=self.settings.aws_region,
                            config=self.config
                            )
