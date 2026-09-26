"""Acesso a banco do diario de sinais.

Le tabelas de outros donos - candle_diario e indice_macro (gestor),
insight_acao (este worker) - e escreve so em sinal_diario e sinal_resultado
(mysql-migrations/V4). SQL explicito em vez de entidade ORM: as tabelas lidas
nao sao deste modulo, e mapea-las aqui criaria um segundo dono do schema.

A Session entra como parametro e o commit fica com quem chama.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

from app.validacao.avaliador import Pregao, ResultadoHorizonte


class RepositorioDiario:
    def fechamentos_do_pregao(self, db, data_pregao: date) -> dict[str, Decimal]:
        linhas = db.execute(
            text("SELECT simbolo, close FROM candle_diario WHERE data = :d AND close IS NOT NULL"),
            {"d": data_pregao},
        )
        return {simbolo: Decimal(str(fechamento)) for simbolo, fechamento in linhas}

    def ultimo_pregao_ate(self, db, data_limite: date) -> date | None:
        return db.execute(
            text("SELECT MAX(data) FROM candle_diario WHERE data <= :d"), {"d": data_limite}
        ).scalar()

    def proximo_pregao(self, db, data_pregao: date) -> date | None:
        return db.execute(
            text("SELECT MIN(data) FROM candle_diario WHERE data > :d"), {"d": data_pregao}
        ).scalar()

    def ultimo_insight(self, db, simbolo: str, inicio_utc: datetime, fim_utc: datetime):
        """Insight mais recente do ativo na janela, ignorando SEM_DADOS."""
        linha = db.execute(
            text(
                "SELECT id, recomendacao, detalhes_json FROM insight_acao "
                "WHERE simbolo = :s AND data_analise >= :ini AND data_analise < :fim "
                "AND recomendacao IS NOT NULL AND recomendacao <> 'SEM_DADOS' "
                "ORDER BY data_analise DESC, id DESC LIMIT 1"
            ),
            {"s": simbolo, "ini": inicio_utc, "fim": fim_utc},
        ).first()
        if linha is None:
            return None
        detalhes = linha[2]
        if isinstance(detalhes, (str, bytes)):
            detalhes = json.loads(detalhes)
        return {"id": linha[0], "recomendacao": linha[1], "detalhes": detalhes or {}}

    def inserir_sinal(self, db, sinal: dict) -> bool:
        """INSERT IGNORE: sinal ja registrado para (ativo, pregao, versao) nao
        e sobrescrito - o diario so aceita inclusao."""
        resultado = db.execute(
            text(
                "INSERT IGNORE INTO sinal_diario (simbolo, data_pregao, versao_regra, recomendacao, "
                "nivel_risco, confianca_score, sinal_momentum, sinal_reversao, preco_fechamento, insight_id) "
                "VALUES (:simbolo, :data_pregao, :versao_regra, :recomendacao, :nivel_risco, "
                ":confianca_score, :sinal_momentum, :sinal_reversao, :preco_fechamento, :insight_id)"
            ),
            sinal,
        )
        return resultado.rowcount == 1

    def sinais_com_horizonte_pendente(self, db, total_horizontes: int) -> list[dict]:
        linhas = db.execute(
            text(
                "SELECT s.id, s.simbolo, s.data_pregao, s.recomendacao "
                "FROM sinal_diario s LEFT JOIN sinal_resultado r ON r.sinal_id = s.id "
                "GROUP BY s.id, s.simbolo, s.data_pregao, s.recomendacao "
                "HAVING COUNT(r.id) < :total ORDER BY s.data_pregao"
            ),
            {"total": total_horizontes},
        )
        return [
            {"id": i, "simbolo": s, "data_pregao": d, "recomendacao": r} for i, s, d, r in linhas
        ]

    def horizontes_avaliados(self, db, sinal_id: int) -> set[int]:
        linhas = db.execute(
            text("SELECT horizonte FROM sinal_resultado WHERE sinal_id = :id"), {"id": sinal_id}
        )
        return {h for (h,) in linhas}

    def serie_de_precos(self, db, simbolo: str, desde: date) -> list[Pregao]:
        linhas = db.execute(
            text(
                "SELECT data, open, close FROM candle_diario "
                "WHERE simbolo = :s AND data >= :d AND open IS NOT NULL AND close IS NOT NULL "
                "ORDER BY data"
            ),
            {"s": simbolo, "d": desde},
        )
        return [Pregao(d, Decimal(str(a)), Decimal(str(f))) for d, a, f in linhas]

    def cdi_diario(self, db, desde: date) -> dict[date, Decimal]:
        linhas = db.execute(
            text(
                "SELECT data, valor FROM indice_macro "
                "WHERE codigo_serie = 'CDI' AND data >= :d AND valor IS NOT NULL"
            ),
            {"d": desde},
        )
        return {d: Decimal(str(v)) for d, v in linhas}

    def inserir_resultado(self, db, sinal_id: int, r: ResultadoHorizonte) -> None:
        db.execute(
            text(
                "INSERT IGNORE INTO sinal_resultado (sinal_id, horizonte, data_entrada, data_saida, "
                "preco_entrada, preco_saida, retorno_bruto, retorno_liquido, retorno_bova11, retorno_cdi, "
                "excesso_bova11, excesso_cdi, acerto, evento_suspeito) VALUES (:sinal_id, :horizonte, "
                ":data_entrada, :data_saida, :preco_entrada, :preco_saida, :retorno_bruto, "
                ":retorno_liquido, :retorno_bova11, :retorno_cdi, :excesso_bova11, :excesso_cdi, "
                ":acerto, :evento_suspeito)"
            ),
            {
                "sinal_id": sinal_id,
                "horizonte": r.horizonte,
                "data_entrada": r.data_entrada,
                "data_saida": r.data_saida,
                "preco_entrada": r.preco_entrada,
                "preco_saida": r.preco_saida,
                "retorno_bruto": r.retorno_bruto,
                "retorno_liquido": r.retorno_liquido,
                "retorno_bova11": r.retorno_bova11,
                "retorno_cdi": r.retorno_cdi,
                "excesso_bova11": r.excesso_bova11,
                "excesso_cdi": r.excesso_cdi,
                "acerto": r.acerto,
                "evento_suspeito": r.evento_suspeito,
            },
        )
