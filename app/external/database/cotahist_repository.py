"""Leitura do preco oficial da B3 (cotacao_b3_diaria, COTAHIST - infra#CTR-13).

Unica porta do worker para o COTAHIST: os insights diarios da camada Base, a
serie tecnica deles e o diario de sinais leem daqui, em vez de cada um montar
SQL proprio. O codigo e o NEGOCIADO no dia (ELET3 em 2020); aqui ele vira o
canonico (AXIA3) pela ativo_identidade, e na data em que os dois negociaram
vence o canonico.

SQL explicito, sem entidade ORM: a tabela e do ETL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import bindparam, text

PREGOES_52_SEMANAS = 252


@dataclass(frozen=True)
class PregaoOficial:
    data: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: int | None

    # Interface que SerieTecnicaService espera de um candle (fechamento
    # ajustado, fechamento, volume): o COTAHIST e bruto, entao o ajustado e None.
    @property
    def fechamento_ajustado(self) -> Decimal | None:
        return None


class RepositorioCotahist:
    def identidades(self, db) -> dict[str, tuple[str, bool]]:
        return {
            s: (c, bool(k))
            for s, c, k in db.execute(
                text("SELECT simbolo, simbolo_canonico, continuidade_preco FROM ativo_identidade")
            )
        }

    def ultimo_pregao_ate(self, db, limite: date) -> date | None:
        return db.execute(
            text("SELECT MAX(data_pregao) FROM cotacao_b3_diaria WHERE data_pregao <= :d"), {"d": limite}
        ).scalar()

    def proximo_pregao(self, db, dia: date) -> date | None:
        return db.execute(
            text("SELECT MIN(data_pregao) FROM cotacao_b3_diaria WHERE data_pregao > :d"), {"d": dia}
        ).scalar()

    def pregoes_entre(self, db, depois_de: date, ate: date) -> list[date]:
        return [
            d for (d,) in db.execute(
                text(
                    "SELECT DISTINCT data_pregao FROM cotacao_b3_diaria "
                    "WHERE data_pregao > :ini AND data_pregao <= :fim ORDER BY data_pregao"
                ),
                {"ini": depois_de, "fim": ate},
            )
        ]

    def series(self, db, simbolos: set[str], desde: date, ate: date | None = None) -> dict[str, list[PregaoOficial]]:
        """Serie diaria por codigo CANONICO, emendando os codigos antigos do
        mesmo papel. Uma consulta so para todos os simbolos."""
        if not simbolos:
            return {}
        identidades = self.identidades(db)
        codigos = set(simbolos) | {s for s, (c, continuo) in identidades.items() if c in simbolos and continuo}
        linhas = db.execute(
            text(
                "SELECT simbolo, data_pregao, abertura, maxima, minima, fechamento, volume "
                "FROM cotacao_b3_diaria WHERE simbolo IN :codigos AND data_pregao >= :desde "
                "AND data_pregao <= :ate AND abertura > 0 AND fechamento > 0 ORDER BY data_pregao"
            ).bindparams(bindparam("codigos", expanding=True)),
            {"codigos": sorted(codigos), "desde": desde, "ate": ate or date.max},
        )
        por_ativo: dict[str, dict[date, tuple[bool, PregaoOficial]]] = {}
        for simbolo, dia, abertura, maxima, minima, fechamento, volume in linhas:
            canonico, continuo = identidades.get(simbolo, (simbolo, True))
            if not continuo or canonico not in simbolos:
                continue
            e_canonico = simbolo == canonico
            atual = por_ativo.setdefault(canonico, {}).get(dia)
            if atual and atual[0] and not e_canonico:
                continue
            por_ativo[canonico][dia] = (
                e_canonico,
                PregaoOficial(dia, Decimal(str(abertura)), Decimal(str(maxima)), Decimal(str(minima)),
                              Decimal(str(fechamento)), None if volume is None else int(volume)),
            )
        return {s: [p for _, p in sorted(d.values(), key=lambda x: x[1].data)] for s, d in por_ativo.items()}

    def listar_ultimos_fechamentos(
        self, db, simbolo: str, intervalo: str = "1d", limite: int = 20
    ) -> list[PregaoOficial]:
        """Mesma assinatura de SerieHistoricaRepository.listar_ultimos_fechamentos:
        a serie tecnica da camada Base troca de fonte sem mudar de codigo."""
        serie = self.series(db, {simbolo}, date.today() - timedelta(days=limite * 3 + 30)).get(simbolo, [])
        return serie[-limite:]
