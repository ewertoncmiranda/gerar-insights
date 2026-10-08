"""Configuração do banco usa Settings como fonte única."""

from __future__ import annotations

from app.config.database_config import ConfigDatabase
from sqlalchemy.exc import OperationalError


class _SettingsFake:
    retry_attempts = 4
    retry_delay = 7


def test_wait_for_mysql_usa_retry_do_settings(monkeypatch):
    config = ConfigDatabase.__new__(ConfigDatabase)
    config.settings = _SettingsFake()
    tentativas = []
    esperas = []
    monkeypatch.setattr("app.config.database_config.time.sleep", esperas.append)

    class _Conexao:
        def __enter__(self):
            if not tentativas:
                tentativas.append("erro")
                raise OperationalError("SELECT 1", {}, Exception("fora do ar"))
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _sql):
            tentativas.append("ok")

    class _Engine:
        def connect(self):
            return _Conexao()

    config.engine = _Engine()

    config.wait_for_mysql()

    assert tentativas == ["erro", "ok"]
    assert esperas == [7]
