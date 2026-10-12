"""Estratégia MOMENTO_PURO para o simulador.

Calcula o retorno 12-1 meses (retorno dos últimos 12 meses excluindo o mês mais recente)
para todos os ativos monitorados em simulador_ativo e grava em simulador_resultado.

A estratégia é exclusiva do simulador e não entra no BacktestRanking nem no backtest de sexta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import json
from logging import Logger
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.external.database.cotahist_repository import RepositorioCotahist

VERSAO_ESTRATEGIA = "MOMENTO_PURO_v1"
# Retorno 12-1 meses: ~252 pregões (12 meses) - ~21 pregões (1 mês) = ~231 pregões
JANELA_MESES_12 = 252
JANELA_MESES_1 = 21
JANELA_MESES_11 = JANELA_MESES_12 - JANELA_MESES_1


@dataclass
class ResultadoMomento:
    ativo_id: int
    simbolo: str
    data_pregao: date
    retorno_pct: Decimal | None
    quintil: int | None
    score: Decimal | None
    parametros_json: dict[str, Any]


class MomentoPuroService:
    def __init__(self, logger: Logger, cotahist: RepositorioCotahist | None = None):
        self._logger = logger
        self._cotahist = cotahist or RepositorioCotahist()

    def executar(self, db: Session, dia: date | None = None) -> list[ResultadoMomento]:
        """Calcula e grava o score diário da estratégia MOMENTO_PURO.

        Args:
            db: Sessão do banco de dados
            dia: Data do pregão (opcional, usa o último pregão disponível se None)

        Returns:
            Lista de resultados calculados
        """
        dia = dia or self._cotahist.ultimo_pregao_ate(db, date.today())
        if dia is None:
            self._logger.warning("Sem COTAHIST no banco; nada a calcular")
            return []

        self._logger.info("MOMENTO_PURO: calculando para pregão %s", dia)

        # Ler ativos monitorados em simulador_ativo
        ativos = self._ler_ativos_monitorados(db)
        if not ativos:
            self._logger.warning("Nenhum ativo monitorado em simulador_ativo")
            return []

        simbolos = {a["simbolo"] for a in ativos}
        self._logger.info("MOMENTO_PURO: %d ativos monitorados", len(simbolos))

        # Ler série histórica para o cálculo de retorno 12-1
        desde = dia - timedelta(days=JANELA_MESES_12 + 30)  # Margem para dias sem pregão
        series = self._cotahist.series(db, simbolos, desde, dia)

        # Calcular retorno 12-1 para cada ativo
        resultados: list[ResultadoMomento] = []
        for ativo in ativos:
            simbolo = ativo["simbolo"]
            ativo_id = ativo["id"]
            serie = series.get(simbolo, [])

            retorno_pct = self._calcular_retorno_12_1(serie, dia)
            if retorno_pct is None:
                self._logger.debug("MOMENTO_PURO: %s sem dados suficientes", simbolo)
                resultados.append(
                    ResultadoMomento(
                        ativo_id=ativo_id,
                        simbolo=simbolo,
                        data_pregao=dia,
                        retorno_pct=None,
                        quintil=None,
                        score=None,
                        parametros_json={"erro": "dados_insuficientes"},
                    )
                )
                continue

            resultados.append(
                ResultadoMomento(
                    ativo_id=ativo_id,
                    simbolo=simbolo,
                    data_pregao=dia,
                    retorno_pct=retorno_pct,
                    quintil=None,  # Será calculado após ter todos os retornos
                    score=retorno_pct,
                    parametros_json={"janela_meses_12": JANELA_MESES_12, "janela_meses_1": JANELA_MESES_1},
                )
            )

        # Calcular quintis (1-5) baseado no ranking dos retornos
        self._calcular_quintis(resultados)

        # Gravar em simulador_resultado
        gravados = 0
        ja_existiam = 0
        for resultado in resultados:
            if self._gravar_resultado(db, resultado):
                gravados += 1
            else:
                ja_existiam += 1

        db.commit()
        self._logger.info(
            "MOMENTO_PURO: %d gravados, %d já existiam, %d sem dados",
            gravados,
            ja_existiam,
            len([r for r in resultados if r.retorno_pct is None]),
        )

        return resultados

    def _ler_ativos_monitorados(self, db: Session) -> list[dict[str, Any]]:
        """Lê ativos ativos de simulador_ativo."""
        linhas = db.execute(
            text("SELECT id, simbolo FROM simulador_ativo WHERE ativo = TRUE")
        )
        return [{"id": id_, "simbolo": simbolo} for id_, simbolo in linhas]

    def _calcular_retorno_12_1(self, serie: list[Any], dia: date) -> Decimal | None:
        """Calcula o retorno 12-1 meses.

        Usa o fechamento de há ~12 meses e o fechamento de há ~1 mês.
        Retorna None se não houver dados suficientes.
        """
        if len(serie) < JANELA_MESES_12:
            return None

        # Encontrar o fechamento mais próximo de há 12 meses
        data_12m = dia - timedelta(days=JANELA_MESES_12)
        data_1m = dia - timedelta(days=JANELA_MESES_1)

        fechamento_12m = None
        fechamento_1m = None

        for pregao in serie:
            if pregao.data <= data_12m:
                fechamento_12m = pregao.fechamento
            if pregao.data <= data_1m:
                fechamento_1m = pregao.fechamento

        if fechamento_12m is None or fechamento_1m is None:
            return None

        if fechamento_12m == 0:
            return None

        retorno = (fechamento_1m - fechamento_12m) / fechamento_12m * 100
        return retorno

    def _calcular_quintis(self, resultados: list[ResultadoMomento]) -> None:
        """Calcula quintis (1-5) baseado no ranking dos retornos.

        Quintil 1 = piores retornos (bottom 20%)
        Quintil 5 = melhores retornos (top 20%)
        """
        # Filtrar apenas resultados com retorno válido
        validos = [r for r in resultados if r.retorno_pct is not None]
        if not validos:
            return

        # Ordenar por retorno
        validos_ordenados = sorted(validos, key=lambda r: r.retorno_pct or Decimal("0"))

        # Dividir em 5 quintis
        n = len(validos_ordenados)
        for i, resultado in enumerate(validos_ordenados):
            quintil = (i * 5) // n + 1
            resultado.quintil = quintil

    def _gravar_resultado(self, db: Session, resultado: ResultadoMomento) -> bool:
        """Grava resultado em simulador_resultado.

        Usa a unique constraint (ativo_id, data_pregao, versao_estrategia) para idempotência.
        Retorna True se gravou um novo registro, False se já existia.
        """
        if resultado.retorno_pct is None:
            # Não grava ativos sem dados suficientes
            return False

        # Verificar se já existe
        existente = db.execute(
            text(
                "SELECT id FROM simulador_resultado "
                "WHERE ativo_id = :ativo_id AND data_pregao = :data_pregao "
                "AND versao_estrategia = :versao"
            ),
            {
                "ativo_id": resultado.ativo_id,
                "data_pregao": resultado.data_pregao,
                "versao": VERSAO_ESTRATEGIA,
            },
        ).scalar()

        if existente is not None:
            return False

        # Inserir novo registro
        db.execute(
            text(
                "INSERT INTO simulador_resultado "
                "(ativo_id, data_pregao, versao_estrategia, quintil, retorno_pct, score, parametros_json) "
                "VALUES (:ativo_id, :data_pregao, :versao, :quintil, :retorno_pct, :score, :parametros_json)"
            ),
            {
                "ativo_id": resultado.ativo_id,
                "data_pregao": resultado.data_pregao,
                "versao": VERSAO_ESTRATEGIA,
                "quintil": resultado.quintil,
                "retorno_pct": resultado.retorno_pct,
                "score": resultado.score,
                "parametros_json": json.dumps(resultado.parametros_json, ensure_ascii=False),
            },
        )
        return True
