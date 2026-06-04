import os

class Settings:

    def __init__(self):
        self.localstack_endpoint = os.getenv('LOCALSTACK_ENDPOINT', 'http://localstack:4566')
        self.queue_name = os.getenv('QUEUE_NAME', 'tratar-ativos')
        self.aws_region = os.getenv('AWS_REGION', 'sa-east-1')
        self.aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', 'test')
        self.aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
        self.dynamo_endpoint = os.getenv('DYNAMO_ENDPOINT', self.localstack_endpoint)
        self.db_driver = os.getenv('DB_DRIVER', 'mysql+pymysql')
        self.db_host = os.getenv('DB_HOST', 'mysql')
        self.db_port = int(os.getenv('DB_PORT', '3306'))
        self.db_user = os.getenv('DB_USER', 'spring')
        self.db_password = os.getenv('DB_PASS', 'spring123')
        self.db_name = os.getenv('DB_NAME', 'minha_base')
        self.retry_attempts = int(os.getenv('RETRY_ATTEMPTS', '3'))
        self.retry_delay = int(os.getenv('RETRY_DELAY', '10'))
        self.database_url = f"{self.db_driver}://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
