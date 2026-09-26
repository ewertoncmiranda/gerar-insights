"""Motor de avaliacao de um sinal. Puro: sem banco, sem rede, sem relogio.

Pergunta que responde: "se alguem tivesse agido neste sinal, quanto teria
ganho ou perdido depois de h pregoes, comparado com o BOVA11 e com o CDI?"

Convencoes (decisoes D1 e D2 do plano, 2026-09-26):

  - Entrada na ABERTURA do pregao seguinte ao sinal. O sinal usa o fechamento
    do dia; ninguem consegue comprar pelo preco que so existe depois que o
    pregao acabou. Entrar no proprio fechamento e viés de futuro.
  - Saida no FECHAMENTO do h-esimo pregao contado a partir do sinal.
    Horizontes em pregoes: 21, 63 e 126 (~1, 3 e 6 meses uteis).
  - Custo de ida e volta descontado do retorno (padrao 0,10%). IR fica para a
    camada de execucao: depende do mes inteiro do investidor, nao do sinal.
  - CDI acumulado nos dias em que o dinheiro esteve aplicado:
    de data_entrada (inclusive) ate data_saida (exclusive).

O que NAO faz, de proposito: nao ajusta proventos. Com preco bruto (COTAHIST),
um desdobramento aparece como queda de 50% sem ninguem ter vendido; a janela
que contem esse salto e marcada como suspeita e fica fora das estatisticas,
em vez de virar um "erro" da regra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

HORIZONTES_PREGOES: tuple[int, ...] = (21, 63, 126)
CUSTO_IDA_E_VOLTA_PADRAO = Decimal("0.0010")

# Salto de uma sessao para outra a partir do qual a janela vira suspeita de
# evento corporativo (desdobramento, grupamento, bonificacao). 40% em um
# pregao e rarissimo como movimento de mercado em acao liquida.
LIMIAR_SALTO_SUSPEITO = Decimal("0.40")

COMPRA = 1
VENDA = -1
SEM_DIRECAO = 0

_DIRECAO = {
    "COMPRA_FORTE": COMPRA,
    "COMPRA_MODERADA": COMPRA,
    "COMPRA_TECNICA": COMPRA,
    "VENDA_VALUATION": VENDA,
    "VENDA_TECNICA": VENDA,
}


def direcao(recomendacao: str | None) -> int:
    """COMPRA_* aposta em alta, VENDA_* em queda; MANTER e ALERTA nao apostam.

    Sinal sem direcao ainda e avaliado (retorno e excesso), so nao tem
    "acerto": seria inventar uma aposta que a regra nao fez.
    """
    return _DIRECAO.get(recomendacao or "", SEM_DIRECAO)


@dataclass(frozen=True)
class Pregao:
    data: date
    abertura: Decimal
    fechamento: Decimal


@dataclass(frozen=True)
class ResultadoHorizonte:
    horizonte: int
    data_entrada: date
    data_saida: date
    preco_entrada: Decimal
    preco_saida: Decimal
    retorno_bruto: Decimal
    retorno_liquido: Decimal
    retorno_bova11: Decimal | None
    retorno_cdi: Decimal | None
    excesso_bova11: Decimal | None
    excesso_cdi: Decimal | None
    acerto: bool | None
    evento_suspeito: bool


def avaliar(
    data_sinal: date,
    recomendacao: str | None,
    pregoes: list[Pregao],
    horizonte: int,
    benchmark: list[Pregao] | None = None,
    cdi_diario: dict[date, Decimal] | None = None,
    custo_ida_e_volta: Decimal = CUSTO_IDA_E_VOLTA_PADRAO,
) -> ResultadoHorizonte | None:
    """Avalia um sinal num horizonte. None = ainda nao ha pregoes suficientes
    (sinal pendente) ou o dia do sinal nao esta na serie."""
    serie = sorted(pregoes, key=lambda p: p.data)
    indice_sinal = next((i for i, p in enumerate(serie) if p.data == data_sinal), None)
    if indice_sinal is None:
        return None

    indice_entrada = indice_sinal + 1
    indice_saida = indice_sinal + horizonte
    if indice_saida >= len(serie) or horizonte < 1:
        return None

    entrada = serie[indice_entrada]
    saida = serie[indice_saida]
    if not entrada.abertura or not saida.fechamento:
        return None

    retorno_bruto = saida.fechamento / entrada.abertura - 1
    retorno_liquido = retorno_bruto - custo_ida_e_volta

    retorno_bova11 = _retorno_no_periodo(benchmark, entrada.data, saida.data)
    retorno_cdi = _cdi_acumulado(cdi_diario, entrada.data, saida.data)

    sentido = direcao(recomendacao)
    acerto = None if sentido == SEM_DIRECAO else (retorno_liquido * sentido) > 0

    return ResultadoHorizonte(
        horizonte=horizonte,
        data_entrada=entrada.data,
        data_saida=saida.data,
        preco_entrada=entrada.abertura,
        preco_saida=saida.fechamento,
        retorno_bruto=_q(retorno_bruto),
        retorno_liquido=_q(retorno_liquido),
        retorno_bova11=_q(retorno_bova11),
        retorno_cdi=_q(retorno_cdi),
        excesso_bova11=_q(retorno_liquido - retorno_bova11) if retorno_bova11 is not None else None,
        excesso_cdi=_q(retorno_liquido - retorno_cdi) if retorno_cdi is not None else None,
        acerto=acerto,
        evento_suspeito=_tem_salto_suspeito(serie[indice_sinal : indice_saida + 1]),
    )


def _retorno_no_periodo(
    serie: list[Pregao] | None, data_entrada: date, data_saida: date
) -> Decimal | None:
    """Mesma convencao do ativo: abertura da entrada ao fechamento da saida.

    Datas precisam existir na serie do benchmark; sem elas o excesso fica
    nulo em vez de comparar periodos diferentes.
    """
    if not serie:
        return None
    por_data = {p.data: p for p in serie}
    entrada = por_data.get(data_entrada)
    saida = por_data.get(data_saida)
    if not entrada or not saida or not entrada.abertura:
        return None
    return saida.fechamento / entrada.abertura - 1


def _cdi_acumulado(
    cdi_diario: dict[date, Decimal] | None, data_entrada: date, data_saida: date
) -> Decimal | None:
    """Produto de (1 + taxa/100) nos dias uteis do periodo.

    A serie 12 do SGS e a taxa do dia em % ao dia. Periodo sem nenhum ponto
    de CDI devolve None - zero seria dizer que o dinheiro parado rende nada.
    """
    if not cdi_diario:
        return None
    dias = [d for d in cdi_diario if data_entrada <= d < data_saida]
    if not dias:
        return None
    fator = Decimal(1)
    for dia in dias:
        fator *= 1 + cdi_diario[dia] / 100
    return fator - 1


def _tem_salto_suspeito(janela: list[Pregao]) -> bool:
    for anterior, atual in zip(janela, janela[1:]):
        if anterior.fechamento and atual.abertura:
            salto = abs(atual.abertura / anterior.fechamento - 1)
            if salto >= LIMIAR_SALTO_SUSPEITO:
                return True
    return False


def _q(valor: Decimal | None) -> Decimal | None:
    return None if valor is None else valor.quantize(Decimal("0.000001"))
