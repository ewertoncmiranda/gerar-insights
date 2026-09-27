"""Universo do backtest, ano a ano, sem vies de sobrevivencia (infra#TASK-31,
gerar-insights#TASK-51).

Regra (a mesma do ETL, que carrega os balancos desse universo -
etl-fundamentos-cvm RepositorioUniversoSql.listar_simbolos_liquidos):
uma acao entra no universo do ano A se, no ano A-1, teve pelo menos
PREGOES_MINIMOS pregoes e volume financeiro medio de pelo menos
LIQUIDEZ_MINIMA por dia. Medir no ano anterior e o que evita olhar o
futuro; incluir quem depois saiu da bolsa e o que evita o vies de
sobrevivencia do universo "de hoje" (os 31 monitorados).

Ficam de fora:
  - units e fundos (final 11): o LPA da CVM e por acao, nao por unit;
  - BDRs (final 31-39): emissor estrangeiro, sem balanco na CVM - exceto os
    codigos da ativo_identidade (JBSS32 e o BDR da JBS N.V., que tem DFP).
"""

from __future__ import annotations

from sqlalchemy import text

PREGOES_MINIMOS = 200
LIQUIDEZ_MINIMA = 5_000_000  # R$ por dia, media do ano anterior

_SQL = text(
    "SELECT t.simbolo, t.ano + 1 AS ano_universo FROM ("
    "  SELECT simbolo, YEAR(data_pregao) ano, COUNT(*) n, AVG(volume_financeiro) vol"
    "  FROM cotacao_b3_diaria GROUP BY simbolo, YEAR(data_pregao)"
    ") t "
    "WHERE t.n >= :pregoes AND t.vol >= :liquidez AND t.simbolo NOT LIKE '%11' "
    "AND (t.simbolo NOT REGEXP '3[1-9]$' "
    "     OR t.simbolo IN (SELECT simbolo FROM ativo_identidade))"
)


def universo_por_ano(db, identidades: dict[str, tuple[str, bool]]) -> dict[int, set[str]]:
    """ano -> codigos CANONICOS no universo daquele ano (ELET3 em 2020 vira AXIA3).
    Codigo antigo sem continuidade de preco (BRFS3) fica com o proprio codigo."""
    universo: dict[int, set[str]] = {}
    for simbolo, ano in db.execute(_SQL, {"pregoes": PREGOES_MINIMOS, "liquidez": LIQUIDEZ_MINIMA}):
        canonico, continuo = identidades.get(simbolo, (simbolo, True))
        universo.setdefault(int(ano), set()).add(canonico if continuo else simbolo)
    return universo
