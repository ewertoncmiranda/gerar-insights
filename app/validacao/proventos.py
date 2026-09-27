"""Ajuste de retorno total com proventos (Item 3 do plano de precisao,
27/09/2026).

Fonte: provento_distribuido, escrita pelo gestor-ativos-brutos
(ClienteB3Proventos / ServicoAtualizacaoProventos) a partir de um endpoint
publico da B3 - tabela de outro dono, lida aqui por SQL explicito, mesmo
padrao ja usado para candle_diario e indice_macro.

Limite conhecido: a B3 so devolve os proventos aprovados nos ~12 meses
anteriores a cada coleta (confirmado: primeira coleta em 27/09/2026 trouxe
eventos desde 26/09/2025) - nao e "so dali pra frente", e uma janela movel
que anda com a data da coleta. Sinal fora dessa janela fica sem provento
(nao por erro, por ausencia de dado). O backfill de anos mais antigos
continua em aberto.

Convencao: usa a data-com (ultima_data_com_direito), nao a data de
pagamento - e quando o direito e travado e o preco cai no ex, coerente com
somar o provento ao preco bruto (COTAHIST) no mesmo instante. Nao distingue
classe de acao pelo ISIN: quando ON e PN tem o mesmo valor aprovado na mesma
data (o caso comum), conta uma vez; quando os valores divergem, fica o
maior - aproximacao conservadora, nao o valor exato por classe.
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

    Devolve emissor -> {data_com: soma dos proventos naquela data}, sem
    duplicar entre classes de acao (ver docstring do modulo)."""
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
