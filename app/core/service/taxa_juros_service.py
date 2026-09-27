"""Taxa livre de risco (Y do Graham ajustado) - DEC-02: Selic meta vigente.

Le `indice_macro` (codigo 'SELIC', SGS 432, % ao ano), que o gestor grava.
O BCB publica a meta ja com as datas ate a proxima reuniao do Copom, entao a
taxa vigente num dia e a do ponto mais recente ate ele e, na falta dele (so
existem os pontos "a frente"), a do ponto futuro mais proximo - desde que a
no maximo JANELA_FUTURA_DIAS, para nao usar uma meta que ainda nao vale.
"""

from __future__ import annotations

import time
from datetime import date

from sqlalchemy import text

CODIGO_SELIC = "SELIC"
JANELA_FUTURA_DIAS = 60
CACHE_SEGUNDOS = 3600

_SQL = text(
    "SELECT valor, data FROM indice_macro "
    "WHERE codigo_serie = :codigo AND valor IS NOT NULL "
    "AND data <= DATE_ADD(:dia, INTERVAL :janela DAY) "
    "ORDER BY (data > :dia), ABS(DATEDIFF(data, :dia)) LIMIT 1"
)


class TaxaJurosService:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._cache: tuple[float, float, date] | None = None  # (instante, taxa, data)

    def taxa_vigente(self, db, dia: date | None = None) -> tuple[float, date] | None:
        """(taxa % a.a., data do ponto usado) ou None se o banco nao tem Selic."""
        if dia is None and self._cache and self._relogio() - self._cache[0] < CACHE_SEGUNDOS:
            return self._cache[1], self._cache[2]
        linha = db.execute(
            _SQL, {"codigo": CODIGO_SELIC, "dia": dia or date.today(), "janela": JANELA_FUTURA_DIAS}
        ).first()
        if linha is None:
            return None
        taxa, data_ponto = float(linha[0]), linha[1]
        if dia is None:
            self._cache = (self._relogio(), taxa, data_ponto)
        return taxa, data_ponto
