"""Dados como eram conhecidos numa data (point-in-time).

Usado pelo diario (regra v2 em sombra) e pelo backtest. A regra de ouro: no
dia D so existe o balanco cuja data de entrega a CVM (DT_RECEB) e <= D, o
CDI publicado ate D e o IPCA ja divulgado ate D. Qualquer atalho aqui vira
um backtest bonito e falso.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text

from app.core.analysis.regra_v2 import juros_anual_de_cdi_diario

# IPCA do mes M sai por volta do dia 10 de M+1; indice_macro grava o dia 1 de M.
DEFASAGEM_IPCA_DIAS = 42


@dataclass(frozen=True)
class Balanco:
    data_entrega: date
    periodo: date
    tipo_periodo: str
    lpa: float
    vpa: float | None = None


class DadosPontoNoTempo:
    def __init__(
        self,
        balancos: dict[str, list[Balanco]],
        cdi: dict[date, float],
        ipca: dict[date, float],
        selic: dict[date, float] | None = None,
    ):
        self._balancos = {s: sorted(b, key=lambda x: x.data_entrega) for s, b in balancos.items()}
        self._datas_cdi = sorted(cdi)
        self._cdi = cdi
        self._datas_ipca = sorted(ipca)
        self._ipca = ipca
        self._datas_selic = sorted(selic or {})
        self._selic = selic or {}

    @classmethod
    def carregar(cls, db) -> "DadosPontoNoTempo":
        balancos: dict[str, list[Balanco]] = {}
        for simbolo, entrega, periodo, tipo, lpa, vpa in db.execute(
            text(
                "SELECT simbolo, data_entrega, periodo, tipo_periodo, lpa, vpa FROM indicador_fundamentalista "
                "WHERE data_entrega IS NOT NULL AND lpa IS NOT NULL"
            )
        ):
            balancos.setdefault(simbolo, []).append(
                Balanco(entrega, periodo, tipo, float(lpa), None if vpa is None else float(vpa))
            )
        cdi = {
            d: float(v)
            for d, v in db.execute(
                text("SELECT data, valor FROM indice_macro WHERE codigo_serie = 'CDI' AND valor IS NOT NULL")
            )
        }
        ipca = {
            d: float(v)
            for d, v in db.execute(
                text("SELECT data, valor FROM indice_macro WHERE codigo_serie = 'IPCA' AND valor IS NOT NULL")
            )
        }
        selic = {
            d: float(v)
            for d, v in db.execute(
                text("SELECT data, valor FROM indice_macro WHERE codigo_serie = 'SELIC' AND valor IS NOT NULL")
            )
        }
        return cls(balancos, cdi, ipca, selic)

    def anuais_em(self, simbolo: str, dia: date, anos: int = 5) -> tuple[list[float], float | None]:
        """LPAs dos ultimos exercicios anuais ja entregues ate `dia` (mais
        recente primeiro) e o VPA do mais recente - o que o worker le da CVM."""
        conhecidos = sorted(
            (b for b in self._balancos.get(simbolo, []) if b.tipo_periodo == "ANUAL" and b.data_entrega <= dia),
            key=lambda b: b.periodo,
            reverse=True,
        )[:anos]
        vpa = next((b.vpa for b in conhecidos if b.vpa is not None), None)
        return [b.lpa for b in conhecidos], vpa

    def selic_em(self, dia: date) -> float | None:
        """Selic meta (% a.a.) vigente em `dia` (DEC-02); None sem historico."""
        i = bisect.bisect_right(self._datas_selic, dia)
        return self._selic[self._datas_selic[i - 1]] if i else None

    def lpa_em(self, simbolo: str, dia: date, usar_ttm: bool = True) -> tuple[float | None, str]:
        """LPA do documento mais recente ja entregue ate `dia`.

        TTM so ganha do anual quando cobre periodo igual ou mais novo; sem
        nenhum entregue, (None, 'SEM_BALANCO')."""
        conhecidos = [b for b in self._balancos.get(simbolo, []) if b.data_entrega <= dia]
        anuais = [b for b in conhecidos if b.tipo_periodo == "ANUAL"]
        ttms = [b for b in conhecidos if b.tipo_periodo == "TTM"] if usar_ttm else []
        anual = max(anuais, key=lambda b: (b.periodo, b.data_entrega), default=None)
        ttm = max(ttms, key=lambda b: (b.periodo, b.data_entrega), default=None)
        if ttm and (anual is None or ttm.periodo >= anual.periodo):
            return ttm.lpa, f"TTM {ttm.periodo.isoformat()}"
        if anual:
            return anual.lpa, f"ANUAL {anual.periodo.isoformat()}"
        return None, "SEM_BALANCO"

    def juros_em(self, dia: date) -> float | None:
        """CDI anualizado do ultimo dia util com taxa ate `dia`."""
        i = bisect.bisect_right(self._datas_cdi, dia)
        return juros_anual_de_cdi_diario(self._cdi[self._datas_cdi[i - 1]]) if i else None

    def ipca_12m_em(self, dia: date) -> float | None:
        """IPCA acumulado nos 12 ultimos meses JA DIVULGADOS ate `dia`."""
        limite = dia - timedelta(days=DEFASAGEM_IPCA_DIAS)
        i = bisect.bisect_right(self._datas_ipca, limite)
        meses = self._datas_ipca[max(0, i - 12) : i]
        if len(meses) < 12:
            return None
        fator = 1.0
        for mes in meses:
            fator *= 1 + self._ipca[mes] / 100
        return (fator - 1) * 100
