"""Proventos por papel e data juntando as duas fontes (LAC-INS-1).

provento_distribuido (B3, evento com valor exato, ~12 meses por coleta)
prevalece; a DVA (provento_contabil, por periodo) cobre o que vem antes do
primeiro evento da B3 do emissor. Valores em R$ por acao da EPOCA (brutos):
quem trabalha com preco ajustado multiplica pelo fator do evento corporativo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.fatores.proventos_contabeis import combinar, eventos_por_data
from app.fatores.repositorio import RepositorioFatores
from app.validacao.proventos import agrupar_por_papel_e_data


class FonteProventos:
    def __init__(self, b3_por_papel: dict[str, dict[date, Decimal]], dva_por_cnpj: dict, datas_ex: dict[str, list[date]],
                 cnpj_de: dict[str, str]):
        self._b3 = b3_por_papel
        self._dva = dva_por_cnpj
        self._datas_ex = datas_ex
        self._cnpj = cnpj_de
        self._cache: dict[str, dict[date, Decimal]] = {}

    @classmethod
    def carregar(cls, db, repositorio: RepositorioFatores | None = None) -> "FonteProventos":
        repositorio = repositorio or RepositorioFatores()
        cnpj_de = repositorio.cnpj_por_simbolo(db)
        b3 = agrupar_por_papel_e_data(
            db.execute(text(
                "SELECT simbolo, isin, tipo, ultima_data_com_direito, valor_por_acao FROM provento_distribuido"
            )).all(),
            repositorio.isin_por_simbolo(db),
        )
        return cls(b3, repositorio.proventos_contabeis(db), repositorio.datas_ex_de_provento(db),
                   cnpj_de)

    def do_papel(self, simbolo: str) -> dict[date, Decimal]:
        if simbolo not in self._cache:
            b3 = self._b3.get(simbolo, {})
            registros = self._dva.get(self._cnpj.get(simbolo, ""), [])
            dva = eventos_por_data(registros, self._datas_ex.get(simbolo, []), min(b3) if b3 else None)
            self._cache[simbolo] = combinar(dva, b3)
        return self._cache[simbolo]

    def em_12_meses(self, simbolo: str, referencia: date) -> float | None:
        """Soma por acao com data em [referencia - 365 dias, referencia). None
        quando o papel nao tem nenhuma fonte (sem dado, nao zero)."""
        eventos = self.do_papel(simbolo)
        if not eventos:
            return None
        inicio = date.fromordinal(referencia.toordinal() - 365)
        return float(sum((v for d, v in eventos.items() if inicio <= d < referencia), Decimal(0)))
