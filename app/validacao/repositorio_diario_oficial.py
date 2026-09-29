"""Diario de sinais sobre o preco OFICIAL da B3 (proposta 3 do monitoramento
em camadas, 2026-09-27).

Especializa RepositorioDiario trocando so a fonte de preco e a busca do
insight - o resto (insercao, pendentes, CDI, proventos, resultados) e herdado:
  - preco: cotacao_b3_diaria (COTAHIST), o mesmo do backtest, em vez das velas
    da BRAPI - backtest e diario medem com a mesma regua;
  - universo: a camada Base do pregao (universo liquido do ano mais os
    cadastrados), que e quem tem insight diario;
  - insight: SO o da camada Base marcado com o PREGAO do preco
    (data_pregao_referencia). O COTAHIST chega com um dia de atraso, entao
    casar pela hora em que a analise rodou juntaria preco de um dia com sinal
    de outro. Ate 2026-09-29 havia fallback para o insight intradiario da
    BRAPI na janela de horario; ele registrou AXIA3 no pregao 28/09 sem o
    resto do universo (plano de atualizacao diaria, D2: sinal so com preco
    oficial). Sem insight do COTAHIST, o ativo fica em sem_insight e o
    insights_diarios --recuperar preenche o buraco.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.core.service.insights_diarios_service import universo_da_camada_base
from app.external.database.cotahist_repository import RepositorioCotahist
from app.validacao.avaliador import Pregao
from app.validacao.repositorio_diario import RepositorioDiario
from app.validacao.universo import universo_por_ano


class RepositorioDiarioOficial(RepositorioDiario):
    def __init__(self, cotahist: RepositorioCotahist | None = None):
        self._cotahist = cotahist or RepositorioCotahist()

    def fechamentos_do_pregao(self, db, data_pregao: date):
        simbolos = universo_da_camada_base(db, self._cotahist, data_pregao)
        series = self._cotahist.series(db, simbolos, data_pregao, data_pregao)
        return {s: serie[-1].fechamento for s, serie in series.items() if serie}

    def ultimo_pregao_ate(self, db, data_limite: date) -> date | None:
        return self._cotahist.ultimo_pregao_ate(db, data_limite)

    def proximo_pregao(self, db, data_pregao: date) -> date | None:
        return self._cotahist.proximo_pregao(db, data_pregao)

    def pregoes_a_registrar(self, db, ate: date, maximo: int = 10, revisitar: int = 5) -> list[date]:
        """Pregoes do COTAHIST ainda sem sinal: a rotina recupera dias perdidos
        (maquina desligada, COTAHIST atrasado) sem --data manual.

        Revisita tambem os `revisitar` ultimos pregoes ja registrados: um dia
        registrado pela metade (insights ainda nao gerados na hora) ficava
        para sempre incompleto, porque so o MAX(data_pregao) era olhado.
        registrar e idempotente, entao revisitar so completa o que falta.
        """
        base = db.execute(
            text(
                "SELECT MIN(data_pregao) FROM ("
                "  SELECT DISTINCT data_pregao FROM sinal_diario "
                "  ORDER BY data_pregao DESC LIMIT :n"
                ") recentes"
            ),
            {"n": revisitar},
        ).scalar()
        if base is None:
            ultimo_pregao = self.ultimo_pregao_ate(db, ate)
            return [ultimo_pregao] if ultimo_pregao else []
        # pregoes_entre exclui o limite inferior: um dia antes inclui a base.
        return self._cotahist.pregoes_entre(db, base - timedelta(days=1), ate)[-maximo:]

    def ultimo_insight(self, db, simbolo: str, inicio_utc: datetime, fim_utc: datetime,
                       data_pregao: date | None = None):
        if data_pregao is None:
            return super().ultimo_insight(db, simbolo, inicio_utc, fim_utc)
        linha = db.execute(
            text(
                "SELECT id, recomendacao, detalhes_json FROM insight_acao "
                "WHERE simbolo = :s AND recomendacao IS NOT NULL AND recomendacao <> 'SEM_DADOS' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(detalhes_json, '$.data_pregao_referencia')) = :d "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"s": simbolo, "d": data_pregao.isoformat()},
        ).first()
        if linha is None:
            return None
        detalhes = json.loads(linha[2]) if isinstance(linha[2], (str, bytes)) else linha[2]
        return {"id": linha[0], "recomendacao": linha[1], "detalhes": detalhes or {}}

    def series_da_carteira(self, db, desde: date) -> dict[str, list[Pregao]]:
        """Series oficiais dos ativos que estiveram no universo desde `desde`:
        serie do proprio sinal e regua (media) - a mesma carteira do backtest."""
        identidades = self._cotahist.identidades(db)
        anos = {ano: membros for ano, membros in universo_por_ano(db, identidades).items() if ano >= desde.year}
        cadastrados = {s for (s,) in db.execute(text("SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE"))}
        simbolos = set().union(cadastrados, *anos.values())
        return {
            s: [Pregao(p.data, p.abertura, p.fechamento) for p in serie]
            for s, serie in self._cotahist.series(db, simbolos, desde).items()
        }
