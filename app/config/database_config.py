import time

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config.settings import Settings

Base = declarative_base()


class ConfigDatabase:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.db = self.settings.database_url
        self.engine = create_engine(
            self.db,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )
        self.wait_for_mysql()
        self.session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def wait_for_mysql(self):
        retry_attempts = self.settings.retry_attempts
        retry_delay = self.settings.retry_delay
        total_wait_time = retry_attempts * retry_delay
        for attempt in range(1, retry_attempts + 1):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    return
            except OperationalError as e:
                if attempt < retry_attempts:
                    time.sleep(retry_delay)
                else:
                    error_msg = (
                        f"\n{'=' * 70}\n"
                        f"CRITICAL: Database is unavailable\n"
                        f"{'=' * 70}\n"
                        f"MySQL did not respond after {retry_attempts} attempts\n"
                        f"(with interval of {retry_delay}s each = ~{total_wait_time}s total)\n"
                        f"\nVerify:\n"
                        f"  - Environment variables (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME)\n"
                        f"  - MySQL container status: docker ps\n"
                        f"  - MySQL logs: docker logs mysql\n"
                        f"{'=' * 70}\n"
                    )
                    print(error_msg)
                    raise Exception(error_msg) from e
