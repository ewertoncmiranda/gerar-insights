"""Inbox transacional: não existe janela entre registrar a chave e os efeitos."""
from sqlalchemy import text


def reservar_evento(session, consumidor, chave):
    resultado = session.execute(text(
        "INSERT IGNORE INTO evento_processado (consumidor, dedup_key) "
        "VALUES (:consumidor, :chave)"
    ), {"consumidor": consumidor, "chave": chave})
    return resultado.rowcount == 1
