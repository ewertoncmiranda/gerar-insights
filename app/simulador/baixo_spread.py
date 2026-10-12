"""Estratégia BAIXO_SPREAD para o simulador.

Usa a métrica de microestrutura já calculada pelo ETL/infra V24
(`ativo_liquidez_diaria.spread_estimado_63d`) como critério principal:
quanto menor o spread estimado, melhor o quintil. A margem de segurança de
Graham do último insight conhecido até o pregão funciona apenas como desempate.

A estratégia é exclusiva do simulador e grava diretamente em `simulador_resultado`;
não entra no BacktestRanking nem no backtest semanal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json
from logging import Logger
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.external.database.cotahist_repository import RepositorioCotahist

VERSAO_ESTRATEGIA = "BAIXO_SPREAD_v1"


@dataclass
class ResultadoBaixoSpread:
    ativo_id: int
    simbolo: str
    data_pregao: date
    spread_estimado_63d: Decimal | None
    margem_graham: Decimal | None
    quintil: int | None
    score: Decimal | None
    parametros_json: dict[str, Any]


class BaixoSpreadService:
    def __init__(self, logger: Logger, cotahist: RepositorioCotahist | None = None):
        self._logger = logger
        self._cotahist = cotahist or RepositorioCotahist()

    def executar(self, db: Session, dia: date | None = None) -> list[ResultadoBaixoSpread]:
        dia = dia or self._cotahist.ultimo_pregao_ate(db, date.today())
        if dia is None:
            self._logger.warning("Sem COTAHIST no banco; nada a calcular")
            return []

        ativos = self._ler_ativos_monitorados(db)
        if not ativos:
            self._logger.warning("Nenhum ativo monitorado em simulador_ativo")
            return []

        simbolos = {a["simbolo"] for a in ativos}
        liquidez = self._ler_liquidez(db, simbolos, dia)
        margens = self._ler_margens_graham(db, simbolos, dia)

        resultados = [
            self._resultado_para(ativo, dia, liquidez.get(ativo["simbolo"]), margens.get(ativo["simbolo"]))
            for ativo in ativos
        ]
        self._calcular_quintis(resultados)

        gravados = 0
        ja_existiam = 0
        for resultado in resultados:
            if self._gravar_resultado(db, resultado):
                gravados += 1
            else:
                ja_existiam += 1

        db.commit()
        self._logger.info(
            "BAIXO_SPREAD: %d gravados, %d já existiam, %d sem spread",
            gravados,
            ja_existiam,
            len([r for r in resultados if r.spread_estimado_63d is None]),
        )
        return resultados

    def _resultado_para(
        self,
        ativo: dict[str, Any],
        dia: date,
        spread_estimado_63d: Decimal | None,
        margem_graham: Decimal | None,
    ) -> ResultadoBaixoSpread:
        if spread_estimado_63d is None:
            return ResultadoBaixoSpread(
                ativo_id=ativo["id"],
                simbolo=ativo["simbolo"],
                data_pregao=dia,
                spread_estimado_63d=None,
                margem_graham=margem_graham,
                quintil=None,
                score=None,
                parametros_json={"erro": "spread_estimado_ausente"},
            )

        # Score crescente = melhor. Spread menor recebe score maior; margem entra
        # como desempate pequeno, sem mudar a natureza da estratégia.
        desempate = (margem_graham or Decimal("0")) / Decimal("1000000")
        score = -spread_estimado_63d + desempate
        return ResultadoBaixoSpread(
            ativo_id=ativo["id"],
            simbolo=ativo["simbolo"],
            data_pregao=dia,
            spread_estimado_63d=spread_estimado_63d,
            margem_graham=margem_graham,
            quintil=None,
            score=score,
            parametros_json={
                "criterio": "menor_spread_estimado_63d",
                "desempate": "margem_graham_ultimo_insight_ate_pregao",
                "spread_estimado_63d": str(spread_estimado_63d),
                "margem_graham": None if margem_graham is None else str(margem_graham),
            },
        )

    def _ler_ativos_monitorados(self, db: Session) -> list[dict[str, Any]]:
        linhas = db.execute(text("SELECT id, simbolo FROM simulador_ativo WHERE ativo = TRUE"))
        return [{"id": id_, "simbolo": simbolo} for id_, simbolo in linhas]

    def _ler_liquidez(self, db: Session, simbolos: set[str], dia: date) -> dict[str, Decimal | None]:
        if not simbolos:
            return {}
        linhas = db.execute(
            text(
                "SELECT l.simbolo, l.spread_estimado_63d "
                "FROM ativo_liquidez_diaria l "
                "JOIN ("
                "  SELECT simbolo, MAX(data_pregao) data_pregao "
                "  FROM ativo_liquidez_diaria "
                "  WHERE simbolo IN :simbolos AND data_pregao <= :dia "
                "  GROUP BY simbolo"
                ") ult ON ult.simbolo = l.simbolo AND ult.data_pregao = l.data_pregao"
            ).bindparams(bindparam("simbolos", expanding=True)),
            {"simbolos": sorted(simbolos), "dia": dia},
        )
        return {simbolo: None if spread is None else Decimal(str(spread)) for simbolo, spread in linhas}

    def _ler_margens_graham(self, db: Session, simbolos: set[str], dia: date) -> dict[str, Decimal | None]:
        if not simbolos:
            return {}
        linhas = db.execute(
            text(
                "SELECT i.simbolo, i.margem_seguranca_percent "
                "FROM insight_acao i "
                "JOIN ("
                "  SELECT simbolo, MAX(data_analise) data_analise "
                "  FROM insight_acao "
                "  WHERE simbolo IN :simbolos AND DATE(data_analise) <= :dia "
                "  GROUP BY simbolo"
                ") ult ON ult.simbolo = i.simbolo AND ult.data_analise = i.data_analise"
            ).bindparams(bindparam("simbolos", expanding=True)),
            {"simbolos": sorted(simbolos), "dia": dia},
        )
        return {simbolo: None if margem is None else Decimal(str(margem)) for simbolo, margem in linhas}

    def _calcular_quintis(self, resultados: list[ResultadoBaixoSpread]) -> None:
        validos = [r for r in resultados if r.score is not None]
        if not validos:
            return
        ordenados = sorted(validos, key=lambda r: r.score or Decimal("0"))
        n = len(ordenados)
        for i, resultado in enumerate(ordenados):
            resultado.quintil = (i * 5) // n + 1

    def _gravar_resultado(self, db: Session, resultado: ResultadoBaixoSpread) -> bool:
        if resultado.score is None:
            return False
        existente = db.execute(
            text(
                "SELECT id FROM simulador_resultado "
                "WHERE ativo_id = :ativo_id AND data_pregao = :data_pregao "
                "AND versao_estrategia = :versao"
            ),
            {"ativo_id": resultado.ativo_id, "data_pregao": resultado.data_pregao, "versao": VERSAO_ESTRATEGIA},
        ).scalar()
        if existente is not None:
            return False

        db.execute(
            text(
                "INSERT INTO simulador_resultado "
                "(ativo_id, data_pregao, versao_estrategia, quintil, retorno_pct, score, parametros_json) "
                "VALUES (:ativo_id, :data_pregao, :versao, :quintil, NULL, :score, :parametros_json)"
            ),
            {
                "ativo_id": resultado.ativo_id,
                "data_pregao": resultado.data_pregao,
                "versao": VERSAO_ESTRATEGIA,
                "quintil": resultado.quintil,
                "score": resultado.score,
                "parametros_json": json.dumps(resultado.parametros_json, ensure_ascii=False),
            },
        )
        return True
