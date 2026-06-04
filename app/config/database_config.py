import os
import time

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config.settings import Settings

Base = declarative_base()
RETRY_ATTEMPTS = int(os.getenv('RETRY_ATTEMPTS', 3))
RETRY_DELAY = int(os.getenv('RETRY_DELAY', 10))


class ConfigDatabase:
    def __init__(self):
        self.db = Settings().database_url
        self.engine = create_engine(
            self.db,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )
        self.wait_for_mysql()
        self.session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def wait_for_mysql(self):
        total_wait_time = RETRY_ATTEMPTS * RETRY_DELAY
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    return
            except OperationalError as e:
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_DELAY)
                else:
                    error_msg = (
                        f"\n{'=' * 70}\n"
                        f"CRITICAL: Database is unavailable\n"
                        f"{'=' * 70}\n"
                        f"MySQL did not respond after {RETRY_ATTEMPTS} attempts\n"
                        f"(with interval of {RETRY_DELAY}s each = ~{total_wait_time}s total)\n"
                        f"\nVerify:\n"
                        f"  - Environment variables (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME)\n"
                        f"  - MySQL container status: docker ps\n"
                        f"  - MySQL logs: docker logs mysql\n"
                        f"{'=' * 70}\n"
                    )
                    print(error_msg)
                    raise Exception(error_msg) from e


