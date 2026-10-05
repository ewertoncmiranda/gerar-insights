"""Integração opcional no MySQL efêmero de infra/compose.contract-tests.yml."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.external.database.evento_repository import reservar_evento

URL = os.getenv("CONTRACT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Defina CONTRACT_TEST_DATABASE_URL para MySQL isolado")


def test_concorrencia_reentrega_e_rollback_mysql():
    engine = create_engine(URL)
    chave = uuid4().hex.ljust(64, "0")
    barreira = Barrier(3)

    def entregar():
        barreira.wait()
        with Session(engine) as session, session.begin():
            novo = reservar_evento(session, "teste", chave)
            if novo:
                session.execute(text("INSERT INTO historico_acoes (simbolo, dedup_key) VALUES ('TEST3', :chave)"), {"chave": chave})
            return novo

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(lambda _: entregar(), range(3))) == [False, False, True]
    with Session(engine) as session, session.begin():
        assert not reservar_evento(session, "teste", chave)
        assert session.execute(text("SELECT COUNT(*) FROM historico_acoes WHERE dedup_key=:chave"), {"chave": chave}).scalar_one() == 1

    outra = uuid4().hex.ljust(64, "0")
    with Session(engine) as session:
        assert reservar_evento(session, "teste", outra)
        session.rollback()
    with Session(engine) as session, session.begin():
        assert reservar_evento(session, "teste", outra)
    engine.dispose()
