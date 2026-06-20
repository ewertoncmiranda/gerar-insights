import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


def load_environment():
    env_file = os.getenv('ENV_FILE', '.env.local')
    project_root = Path(__file__).resolve().parents[2]
    env_path = Path(env_file)

    if not env_path.is_absolute():
        candidates = [
            project_root / env_path,
            project_root / 'env' / env_path.name,
        ]
        env_path = next((path for path in candidates if path.exists()), candidates[0])

    load_dotenv(env_path, override=False)


def _is_docker_environment(environment):
    return environment.lower() in {'docker', 'container', 'compose'}


def _get_int(name, default):
    value = os.getenv(name)
    if value is None or value == '':
        return default
    return int(value)


load_environment()


class Settings:

    def __init__(self):
        self.environment = os.getenv('ENVIRONMENT', 'local').lower()
        self.is_docker = _is_docker_environment(self.environment)

        default_localstack_endpoint = 'http://localstack:4566' if self.is_docker else 'http://localhost:4566'
        default_db_host = 'mysql' if self.is_docker else 'localhost'
        default_db_port = 3306 if self.is_docker else 3305

        self.localstack_endpoint = os.getenv('LOCALSTACK_ENDPOINT', default_localstack_endpoint)
        self.queue_name = os.getenv('QUEUE_NAME', 'tratar-ativos')
        self.aws_region = os.getenv('AWS_REGION', 'sa-east-1')
        self.aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', 'test')
        self.aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
        self.dynamo_endpoint = os.getenv('DYNAMO_ENDPOINT', self.localstack_endpoint)
        self.db_driver = os.getenv('DB_DRIVER', 'mysql+pymysql')
        self.db_host = os.getenv('DB_HOST', default_db_host)
        self.db_port = _get_int('DB_PORT', default_db_port)
        self.db_user = os.getenv('DB_USER', 'spring')
        self.db_password = os.getenv('DB_PASS', 'spring123')
        self.db_name = os.getenv('DB_NAME', 'minha_base')
        self.retry_attempts = _get_int('RETRY_ATTEMPTS', 3)
        self.retry_delay = _get_int('RETRY_DELAY', 10)
        self._normalize_local_database_host()
        self.database_url = self._build_database_url()
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')

    def _normalize_local_database_host(self):
        if self.is_docker:
            return

        if self.db_host.lower() == 'mysql':
            self.db_host = 'localhost'
            if self.db_port == 3306:
                self.db_port = 3305

    def _build_database_url(self):
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return f"{self.db_driver}://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
