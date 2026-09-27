"""LPA dos ultimos exercicios e VPA da CVM, como conhecidos hoje (ISS-F2).

Le `indicador_fundamentalista` (escrita pelo etl-fundamentos-cvm) so com
balanco ja entregue (`data_entrega <= hoje`, infra#CTR-13). O simbolo do
snapshot da BRAPI ja e o canonico, o mesmo que o ETL grava (infra#CTR-12).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

_SQL = text(
    "SELECT lpa, vpa FROM indicador_fundamentalista "
    "WHERE simbolo = :s AND tipo_periodo = 'ANUAL' AND data_entrega IS NOT NULL "
    "AND data_entrega <= :dia ORDER BY periodo DESC LIMIT :n"
)


class FundamentosCvmService:
    def historico(self, db, simbolo: str, dia: date | None = None, anos: int = 5) -> tuple[list[float], float | None]:
        """(LPAs anuais, mais recente primeiro; VPA do exercicio mais recente)."""
        linhas = db.execute(_SQL, {"s": simbolo, "dia": dia or date.today(), "n": anos}).all()
        lpas = [float(lpa) for lpa, _ in linhas if lpa is not None]
        vpa = next((float(v) for _, v in linhas if v is not None), None)
        return lpas, vpa
