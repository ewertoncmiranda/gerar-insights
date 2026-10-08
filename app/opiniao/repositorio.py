"""Acesso a banco da opiniao por horizonte.

Le insight_acao (este worker), fator_valor/fator_definicao (Plano LAC, V16) e comunicado_cvm
(ETL); escreve so em opiniao_ia (mysql-migrations/V22), que e SO INCLUSAO: a opiniao de um
dia nunca e reescrita, para que o diario possa mede-la depois sem olhar o futuro. SQL
explicito: as tabelas lidas nao sao deste modulo. A Session entra como parametro.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import bindparam, text


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

    # --- Plano GEM ---------------------------------------------------------

    def favoritos_para_gemini(self, db) -> list[str]:
        try:
            linhas = db.execute(text(
                "SELECT simbolo FROM ativo_monitorado "
                "WHERE ativo = TRUE AND tipo_coleta = 'COTACAO_E_HISTORICO' ORDER BY simbolo"
            ))
            return [r[0] for r in linhas]
        except Exception:  # noqa: BLE001 - bases antigas seguem sem prioridade de favorito
            db.rollback()
            return []

    def monitorados_ativos(self, db) -> list[str]:
        try:
            linhas = db.execute(text("SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE ORDER BY simbolo"))
            return [r[0] for r in linhas]
        except Exception:  # noqa: BLE001
            db.rollback()
            return []

    def com_mudanca_de_opiniao(self, db, data_pregao: date, simbolos: list[str]) -> list[str]:
        """Comparação leve: conjunto opinião/risco de hoje contra pregão anterior em opiniao_ia."""
        if not simbolos:
            return []
        try:
            anterior = db.execute(
                text("SELECT MAX(data_pregao) FROM opiniao_ia WHERE data_pregao < :d"), {"d": data_pregao}
            ).scalar()
            if anterior is None:
                return []
            linhas = db.execute(text(
                "SELECT h.simbolo FROM opiniao_ia h LEFT JOIN opiniao_ia a "
                "ON a.simbolo = h.simbolo AND a.horizonte_pregoes = h.horizonte_pregoes "
                "AND a.data_pregao = :a AND a.origem = h.origem "
                "WHERE h.data_pregao = :d AND h.simbolo IN :s "
                "AND (a.id IS NULL OR a.opiniao <> h.opiniao OR a.risco <> h.risco) "
                "GROUP BY h.simbolo ORDER BY h.simbolo"
            ).bindparams(bindparam("s", expanding=True)),
                {"d": data_pregao, "a": anterior, "s": simbolos})
            return [r[0] for r in linhas]
        except Exception:  # noqa: BLE001
            db.rollback()
            return []

    def com_variacao_incomum(self, db, data_pregao: date, simbolos: list[str]) -> list[str]:
        if not simbolos:
            return []
        try:
            linhas = db.execute(text(
                "WITH ret AS ("
                " SELECT simbolo, data_pregao, fechamento / LAG(fechamento) OVER "
                " (PARTITION BY simbolo ORDER BY data_pregao) - 1 AS r "
                " FROM cotacao_b3_diaria WHERE simbolo IN :s AND data_pregao <= :d"
                "), hist AS ("
                " SELECT simbolo, STDDEV_SAMP(r) AS dp FROM ("
                "  SELECT simbolo, r, ROW_NUMBER() OVER (PARTITION BY simbolo ORDER BY data_pregao DESC) rn "
                "  FROM ret WHERE data_pregao < :d AND r IS NOT NULL"
                " ) x WHERE rn <= 63 GROUP BY simbolo"
                ") SELECT r.simbolo FROM ret r JOIN hist h ON h.simbolo = r.simbolo "
                "WHERE r.data_pregao = :d AND h.dp IS NOT NULL AND ABS(r.r) > 2 * h.dp ORDER BY r.simbolo"
            ).bindparams(bindparam("s", expanding=True)),
                {"d": data_pregao, "s": simbolos})
            return [r[0] for r in linhas]
        except Exception:  # noqa: BLE001
            db.rollback()
            return []

    def por_liquidez(self, db, simbolos: list[str]) -> list[str]:
        if not simbolos:
            return []
        try:
            linhas = db.execute(text(
                "SELECT simbolo FROM fator_valor WHERE fator_codigo = 'LIQUIDEZ_63D' AND simbolo IN :s "
                "AND data_referencia = (SELECT MAX(data_referencia) FROM fator_valor WHERE fator_codigo = 'LIQUIDEZ_63D') "
                "ORDER BY valor DESC"
            ).bindparams(bindparam("s", expanding=True)), {"s": simbolos})
            return [r[0] for r in linhas]
        except Exception:  # noqa: BLE001
            db.rollback()
            return []

    def opinioes_modelo_por_hash(self, db, simbolo: str, data_pregao: date, dossie_hash: str) -> list[dict]:
        linhas = db.execute(text(
            "SELECT horizonte_pregoes, opiniao, risco, justificativa_json, invalida_json, dados_ausentes_json, "
            "evidencias_json, modelo, versao_prompt, versao_regra, dossie_hash, insight_id "
            "FROM opiniao_ia WHERE simbolo = :s AND data_pregao < :d AND dossie_hash = :hash "
            "AND origem = 'MODELO' ORDER BY data_pregao DESC"
        ), {"s": simbolo, "d": data_pregao, "hash": dossie_hash})
        vistos: set[int] = set()
        saida = []
        for r in linhas:
            h = int(r[0])
            if h in vistos:
                continue
            vistos.add(h)
            saida.append({
                "simbolo": simbolo, "data_pregao": data_pregao, "horizonte_pregoes": h,
                "opiniao": r[1], "risco": r[2], "justificativa_json": r[3], "invalida_json": r[4],
                "dados_ausentes_json": r[5], "evidencias_json": r[6], "modelo": r[7],
                "versao_prompt": r[8], "versao_regra": r[9], "origem": "MODELO", "tentativas": 0,
                "dossie_hash": r[10], "insight_id": r[11],
            })
        return saida
