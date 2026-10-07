"""Acesso a banco da opiniao por horizonte.

Le insight_acao (este worker), fator_valor/fator_definicao (Plano LAC, V16) e comunicado_cvm
(ETL); escreve so em opiniao_ia (mysql-migrations/V22), que e SO INCLUSAO: a opiniao de um
dia nunca e reescrita, para que o diario possa mede-la depois sem olhar o futuro. SQL
explicito: as tabelas lidas nao sao deste modulo. A Session entra como parametro.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text


class RepositorioOpiniao:
    def ultimo_insight(self, db, simbolo: str, data_pregao: date):
        """Insight mais recente do ativo para o pregao (ignora SEM_DADOS)."""
        linha = db.execute(
            text(
                "SELECT id, detalhes_json FROM insight_acao "
                "WHERE simbolo = :s AND recomendacao IS NOT NULL AND recomendacao <> 'SEM_DADOS' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.data_pregao_referencia')) = :d "
                "ORDER BY data_analise DESC, id DESC LIMIT 1"
            ),
            {"s": simbolo, "d": data_pregao.isoformat()},
        ).first()
        if linha is None:
            return None
        detalhes = linha[1]
        if isinstance(detalhes, (str, bytes)):
            detalhes = json.loads(detalhes)
        return {"id": linha[0], "detalhes": detalhes or {}}

    def fatores_recentes(self, db, simbolo: str) -> list[dict]:
        """Ultimo valor de cada fator ativo (a idade e avaliada nas regras, nao aqui)."""
        try:
            linhas = db.execute(
                text(
                    "SELECT fv.fator_codigo, fd.familia, fd.descricao, fd.direcao_esperada, "
                    "fv.data_referencia, fv.valor, fv.percentil_universo "
                    "FROM fator_valor fv JOIN fator_definicao fd "
                    "  ON fd.codigo = fv.fator_codigo AND fd.ativo = TRUE "
                    "WHERE fv.simbolo = :s AND fv.data_referencia = ("
                    "  SELECT MAX(x.data_referencia) FROM fator_valor x "
                    "  WHERE x.simbolo = fv.simbolo AND x.fator_codigo = fv.fator_codigo)"
                ),
                {"s": simbolo},
            )
            return [{"codigo": r[0], "familia": r[1], "descricao": r[2], "direcao_esperada": r[3],
                     "data_referencia": r[4], "valor": r[5], "percentil_universo": r[6]}
                    for r in linhas]
        except Exception:  # noqa: BLE001 - sem a V16 o dossie segue sem fatores, declarando a falta
            db.rollback()
            return []

    def fatos_relevantes_30d(self, db, simbolo: str, hoje: date) -> int:
        try:
            return int(db.execute(
                text(
                    "SELECT COUNT(*) FROM comunicado_cvm c JOIN cvm_ticker t ON t.cnpj = c.cnpj "
                    "WHERE t.simbolo = :s AND c.categoria = 'FATO_RELEVANTE' "
                    "AND c.data_entrega >= DATE_SUB(:h, INTERVAL 30 DAY) AND c.data_entrega <= :h"
                ),
                {"s": simbolo, "h": hoje},
            ).scalar() or 0)
        except Exception:  # noqa: BLE001
            db.rollback()
            return 0

    def simbolos_do_pregao(self, db, data_pregao: date) -> list[str]:
        linhas = db.execute(
            text(
                "SELECT DISTINCT simbolo FROM insight_acao "
                "WHERE recomendacao IS NOT NULL AND recomendacao <> 'SEM_DADOS' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.data_pregao_referencia')) = :d "
                "ORDER BY simbolo"
            ),
            {"d": data_pregao.isoformat()},
        )
        return [r[0] for r in linhas]

    def ultimo_pregao_com_insight(self, db) -> date | None:
        valor = db.execute(
            text("SELECT MAX(JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.data_pregao_referencia'))) "
                 "FROM insight_acao WHERE recomendacao <> 'SEM_DADOS'")
        ).scalar()
        return date.fromisoformat(str(valor)[:10]) if valor else None

    def ja_existe(self, db, simbolo: str, data_pregao: date, horizonte: int, modelo: str,
                  versao_prompt: str) -> bool:
        return db.execute(
            text(
                "SELECT 1 FROM opiniao_ia WHERE simbolo = :s AND data_pregao = :d AND horizonte_pregoes = :h "
                "AND modelo = :m AND versao_prompt = :v LIMIT 1"
            ),
            {"s": simbolo, "d": data_pregao, "h": horizonte, "m": modelo, "v": versao_prompt},
        ).first() is not None

    def gravar(self, db, registro: dict) -> bool:
        """INSERT IGNORE: a chave unica garante uma opiniao por (ativo, pregao, horizonte, modelo, prompt)."""
        resultado = db.execute(
            text(
                "INSERT IGNORE INTO opiniao_ia (simbolo, data_pregao, horizonte_pregoes, opiniao, risco, "
                "justificativa_json, invalida_json, dados_ausentes_json, evidencias_json, modelo, "
                "versao_prompt, versao_regra, origem, tentativas, dossie_hash, insight_id) VALUES "
                "(:simbolo, :data_pregao, :horizonte_pregoes, :opiniao, :risco, :justificativa_json, "
                ":invalida_json, :dados_ausentes_json, :evidencias_json, :modelo, :versao_prompt, "
                ":versao_regra, :origem, :tentativas, :dossie_hash, :insight_id)"
            ),
            registro,
        )
        return bool(resultado.rowcount)
