"""Ajuste de retorno total com proventos (Item 3 do plano de precisao,
27/09/2026).

Fonte: provento_distribuido, escrita pelo gestor-ativos-brutos
(ClienteB3Proventos / ServicoAtualizacaoProventos) a partir de um endpoint
publico da B3 - tabela de outro dono, lida aqui por SQL explicito, mesmo
padrao ja usado para candle_diario e indice_macro.

Limite historico da fonte B3: cada consulta devolve os proventos aprovados nos ~12 meses
anteriores a cada coleta (confirmado: primeira coleta em 27/09/2026 trouxe
eventos desde 26/09/2025). Para backtest de 2017+ o retorno total deve
combinar essa fonte exata com a DVA contabil (`provento_contabil`) quando
disponivel, como faz `app.fatores.fonte_proventos.FonteProventos`.

Convencao: usa a data-com (ultima_data_com_direito), nao a data de
pagamento - e quando o direito e travado e o preco cai no ex, coerente com
somar o provento ao preco bruto (COTAHIST) no mesmo instante. Quando o ISIN
esta disponivel, distingue classe de acao: PETR3 e PETR4 recebem o evento do
seu proprio ISIN. So cai para o agrupamento por emissor quando o mapeamento
ISIN -> ticker ainda nao existe no banco.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal


def codigo_emissor(simbolo: str) -> str:
    """PETR4 -> PETR: a B3 identifica a empresa pelas 4 letras, sem o digito
    da especie de acao - a mesma convencao usada no gestor-ativos-brutos."""
    return re.sub(r"\d+$", "", simbolo)


def agrupar_por_emissor_e_data(linhas) -> dict[str, dict[date, Decimal]]:
    """linhas: iteravel de (simbolo_emissor, tipo, ultima_data_com_direito, valor_por_acao).

    Fallback historico: devolve emissor -> {data_com: soma dos proventos naquela data},
    sem duplicar entre classes. Prefira `agrupar_por_papel_e_data` quando houver ISIN."""
    maior_por_evento: dict[tuple[str, date, str], Decimal] = {}
    for simbolo, tipo, data_com, valor in linhas:
        if data_com is None:
            continue
        chave = (simbolo, data_com, tipo)
        v = Decimal(str(valor))
        if chave not in maior_por_evento or v > maior_por_evento[chave]:
            maior_por_evento[chave] = v

    agrupado: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for (simbolo, data_com, _tipo), valor in maior_por_evento.items():
        agrupado[simbolo][data_com] += valor
    return {s: dict(d) for s, d in agrupado.items()}


def agrupar_por_papel_e_data(
    linhas,
    isin_por_simbolo: dict[str, str],
) -> dict[str, dict[date, Decimal]]:
    """Agrupa proventos pelo ticker correto usando ISIN.

    `linhas`: iteravel de (simbolo_emissor, isin, tipo, ultima_data_com_direito, valor_por_acao).

    Quando `cvm_ticker.isin` conhece a classe, o evento entra apenas no ticker
    daquele ISIN. Quando nao conhece, mantemos fallback por emissor para nao
    perder cobertura operacional em bases ainda nao migradas.
    """
    simbolos_por_isin: dict[str, list[str]] = defaultdict(list)
    for simbolo, isin in isin_por_simbolo.items():
        if isin:
            simbolos_por_isin[isin].append(simbolo)

    agrupado: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    fallback = []
    vistos: set[tuple[str, str, date, str]] = set()
    for emissor, isin, tipo, data_com, valor in linhas:
        if data_com is None:
            continue
        tickers = simbolos_por_isin.get(isin or "")
        if not tickers:
            fallback.append((emissor, tipo, data_com, valor))
            continue
        chave_evento = (emissor, isin, data_com, tipo)
        if chave_evento in vistos:
            continue
        vistos.add(chave_evento)
        v = Decimal(str(valor))
        for ticker in tickers:
            agrupado[ticker][data_com] += v

    for emissor, eventos in agrupar_por_emissor_e_data(fallback).items():
        agrupado[emissor].update(eventos)
    return {s: dict(d) for s, d in agrupado.items()}
