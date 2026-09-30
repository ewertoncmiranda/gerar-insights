"""Proventos por data a partir da DVA (LAC-INS-1). Puro.

A DVA (7.08.04.01 JCP + 7.08.04.02 Dividendos) da o total distribuido POR
PERIODO; o ETL grava em provento_contabil o valor por acao. Aqui ele vira
eventos por data, na convencao do avaliador (data -> valor por acao):

  - Periodos: ITR = trimestre isolado; DFP = ano. O 4o trimestre e o DFP
    menos os ITR do mesmo ano, para nao contar duas vezes.
  - Data: as marcas ex do COTAHIST (ED, EJ, EDJ...) dentro do periodo; o
    valor do periodo e repartido igualmente entre elas (aproximacao: o
    valor de cada evento nao existe na CVM aberta).
  - Sem marca no periodo: vale a data de entrega do documento.
  - provento_distribuido (evento com valor e data-com, da B3) prevalece:
    a DVA so preenche datas anteriores ao primeiro evento dele.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Sufixos do ESPECI no dia ex que indicam dinheiro (dividendo/JCP). EB, EG,
# ES, ER sao bonificacao, grupamento, subscricao e direitos: nao sao caixa.
MARCAS_DE_PROVENTO = frozenset({"ED", "EJ", "EDJ", "EDB", "EDS", "EJS", "EDR", "EJB"})


@dataclass(frozen=True)
class ProventoContabil:
    tipo_doc: str  # DFP | ITR
    dt_ini: date
    dt_fim: date
    data_entrega: date | None
    por_acao: Decimal | None


def periodos_sem_dupla_contagem(registros: list[ProventoContabil]) -> list[ProventoContabil]:
    """ITR como veio; DFP vira o 4o trimestre (ano menos os ITR do ano).
    DFP sem nenhum ITR no ano fica inteiro, como periodo anual."""
    itrs = [r for r in registros if r.tipo_doc == "ITR" and r.por_acao is not None]
    saida = list(itrs)
    for dfp in (r for r in registros if r.tipo_doc == "DFP" and r.por_acao is not None):
        do_ano = [r for r in itrs if dfp.dt_ini <= r.dt_ini and r.dt_fim <= dfp.dt_fim]
        if not do_ano:
            saida.append(dfp)
            continue
        restante = dfp.por_acao - sum((r.por_acao for r in do_ano), Decimal(0))
        inicio_q4 = max(r.dt_fim for r in do_ano)
        saida.append(ProventoContabil("DFP", inicio_q4, dfp.dt_fim, dfp.data_entrega, max(restante, Decimal(0))))
    return saida


def eventos_por_data(
    registros: list[ProventoContabil],
    datas_ex: list[date],
    inicio_fonte_b3: date | None = None,
) -> dict[date, Decimal]:
    """Mapa data -> provento por acao, pronto para o avaliador.

    datas_ex: dias com marca de provento (MARCAS_DE_PROVENTO) do papel.
    inicio_fonte_b3: primeiro evento de provento_distribuido do emissor; da
    DVA so entram datas anteriores a ele."""
    eventos: dict[date, Decimal] = defaultdict(Decimal)
    datas_ex = sorted(set(datas_ex))
    for periodo in periodos_sem_dupla_contagem(registros):
        if not periodo.por_acao or periodo.por_acao <= 0:
            continue
        no_periodo = [d for d in datas_ex if periodo.dt_ini < d <= periodo.dt_fim]
        if no_periodo:
            parcela = periodo.por_acao / len(no_periodo)
            for d in no_periodo:
                eventos[d] += parcela
        elif periodo.data_entrega is not None:
            eventos[periodo.data_entrega] += periodo.por_acao
    if inicio_fonte_b3 is not None:
        return {d: v for d, v in eventos.items() if d < inicio_fonte_b3}
    return dict(eventos)


def combinar(dva: dict[date, Decimal], b3: dict[date, Decimal]) -> dict[date, Decimal]:
    """Uniao das duas fontes; na mesma data, a B3 (valor exato) vence."""
    combinado = dict(dva)
    combinado.update(b3)
    return combinado
