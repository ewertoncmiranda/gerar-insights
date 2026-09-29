"""Insights diarios da camada Base, sem BRAPI (proposta 1 do monitoramento em
camadas, 2026-09-27).

Camadas:
  - Base: todas as acoes do universo liquido do ano (app/validacao/universo.py)
    mais os ativos cadastrados. Um insight por pregao, com o fechamento
    OFICIAL (COTAHIST) e o lucro da CVM, gerado depois da carga noturna.
  - Favoritos: os cadastrados pelo usuario, que alem disso recebem cotacao
    intradiaria da BRAPI no gestor (so para a tela).

Reaproveita o pipeline inteiro: o adaptador snapshot_cotahist monta o mesmo
payload da BRAPI e o FinancialAnalyzerService analisa como sempre. Idempotente:
um insight por (ativo, pregao, versao da regra), pela dedup_key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from logging import Logger

from sqlalchemy import text

from app.core.analysis.versao_regra import VERSAO_REGRA
from app.core.mapper.snapshot_cotahist import payload_de_cotahist
from app.core.service.financial_analyzer_service import FinancialAnalyzerService
from app.core.service.serie_tecnica_service import SerieTecnicaService
from app.external.database.cotahist_repository import RepositorioCotahist
from app.external.database.entity.insight_entity import InsightEntity
from app.external.database.insight_repository import InsightRepository
from app.validacao.ponto_no_tempo import DadosPontoNoTempo
from app.validacao.universo import universo_por_ano

# Janela de preco lida por execucao: cobre as 52 semanas e a serie tecnica.
DIAS_DE_HISTORICO = 400

# Recuperacao: teto de pregoes por execucao. Um mes de maquina desligada cabe;
# acima disso e reprocessamento, e merece um --data explicito por dia.
LIMITE_DE_RECUPERACAO = 30


def ultimo_pregao_com_insight(db) -> date | None:
    """Pregao mais recente que ja tem insight da camada Base (preco do COTAHIST)."""
    valor = db.execute(
        text(
            "SELECT MAX(JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.data_pregao_referencia'))) "
            "FROM insight_acao "
            "WHERE JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.fonte_preco')) = 'B3_COTAHIST'"
        )
    ).scalar()
    return date.fromisoformat(valor) if valor else None


def universo_da_camada_base(db, repositorio: RepositorioCotahist, dia: date) -> set[str]:
    """Universo liquido do ano do pregao mais os ativos cadastrados (canonicos)."""
    identidades = repositorio.identidades(db)
    liquidos = universo_por_ano(db, identidades).get(dia.year, set())
    cadastrados = {s for (s,) in db.execute(text("SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE"))}
    return liquidos | cadastrados


def chave_de_deduplicacao(simbolo: str, dia: date) -> str:
    """64 caracteres (coluna dedup_key): um insight por ativo, pregao e versao."""
    return hashlib.sha256(f"COTAHIST|{simbolo}|{dia.isoformat()}|{VERSAO_REGRA}".encode()).hexdigest()


@dataclass
class ResumoInsightsDiarios:
    data_pregao: date | None = None
    universo: int = 0
    gravados: int = 0
    ja_existiam: int = 0
    sem_dados: list[str] = field(default_factory=list)
    sem_pregao: list[str] = field(default_factory=list)


class InsightsDiariosService:
    def __init__(
        self,
        logger: Logger,
        cotahist: RepositorioCotahist | None = None,
        insights: InsightRepository | None = None,
        analisador: FinancialAnalyzerService | None = None,
        carregar_dados: Callable = DadosPontoNoTempo.carregar,
        universo: Callable = universo_da_camada_base,
        ultimo_com_insight: Callable = ultimo_pregao_com_insight,
    ):
        self._logger = logger
        self._cotahist = cotahist or RepositorioCotahist()
        self._insights = insights or InsightRepository(logger)
        # A serie tecnica tambem sai do COTAHIST: mesma assinatura do
        # repositorio da BRAPI, entao o servico tecnico nao muda (DIP).
        self._analisador = analisador or FinancialAnalyzerService(
            logger, serie_tecnica_service=SerieTecnicaService(repository=self._cotahist)
        )
        self._carregar_dados = carregar_dados
        self._universo = universo
        self._ultimo_com_insight = ultimo_com_insight

    def recuperar(
        self, db, hoje: date | None = None, limite: int = LIMITE_DE_RECUPERACAO
    ) -> list[ResumoInsightsDiarios]:
        """Gera os insights de todo pregao do COTAHIST posterior ao ultimo insight.

        Maquina desligada num dia util deixava o pregao sem insight para sempre
        (sem --data, executar so olha o ultimo). Idempotente: sem pendencia,
        devolve lista vazia; rodar de novo nao grava nada.
        """
        ultimo = self._cotahist.ultimo_pregao_ate(db, hoje or date.today())
        if ultimo is None:
            self._logger.warning("Sem COTAHIST no banco; nada a recuperar")
            return []
        referencia = self._ultimo_com_insight(db)
        if referencia is None:
            # Base vazia: so o ultimo pregao, em vez de gerar um ano inteiro.
            return [self.executar(db, ultimo)]

        pendentes = self._cotahist.pregoes_entre(db, referencia, ultimo)
        if len(pendentes) > limite:
            self._logger.warning(
                "%d pregoes sem insight; recuperando so os %d mais recentes (%s a %s ficam de fora)",
                len(pendentes), limite, pendentes[0], pendentes[-limite - 1],
            )
            pendentes = pendentes[-limite:]
        return [self.executar(db, dia) for dia in pendentes]

    def executar(self, db, dia: date | None = None) -> ResumoInsightsDiarios:
        resumo = ResumoInsightsDiarios()
        dia = dia or self._cotahist.ultimo_pregao_ate(db, date.today())
        if dia is None:
            self._logger.warning("Sem COTAHIST no banco; nada a analisar")
            return resumo
        resumo.data_pregao = dia

        simbolos = self._universo(db, self._cotahist, dia)
        resumo.universo = len(simbolos)
        series = self._cotahist.series(db, simbolos, dia - timedelta(days=DIAS_DE_HISTORICO), dia)
        dados = self._carregar_dados(db)

        for simbolo in sorted(simbolos):
            lpa, _ = dados.lpa_em(simbolo, dia)
            payload = payload_de_cotahist(simbolo, series.get(simbolo, []), lpa, dia)
            if payload is None:
                resumo.sem_pregao.append(simbolo)
                continue
            payload["dedupKey"] = chave_de_deduplicacao(simbolo, dia)
            insight = self._analisador.gerar_insight_fundamentalista(db, payload)
            if insight["recomendacao"] == "SEM_DADOS":
                resumo.sem_dados.append(simbolo)
            detalhes = {
                **insight["detalhes_json"],
                "fonte_preco": payload["fontePreco"],
                "data_pregao_referencia": payload["dataPregaoReferencia"],
            }
            entidade = InsightEntity(
                dedup_key=insight["dedup_key"],
                simbolo=simbolo,
                preco_justo_graham=insight["preco_justo_graham"],
                margem_seguranca_percent=insight["margem_seguranca_percent"],
                recomendacao=insight["recomendacao"],
                detalhes_json=detalhes,
            )
            # salvar devolve o insight ja existente quando a dedup_key repete.
            if self._insights.salvar(db, entidade) is entidade:
                resumo.gravados += 1
            else:
                resumo.ja_existiam += 1
        db.commit()
        return resumo
