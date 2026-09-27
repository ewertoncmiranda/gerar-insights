"""Motor de avaliacao de um sinal. Puro: sem banco, sem rede, sem relogio.

Pergunta que responde: "se alguem tivesse agido neste sinal, quanto teria
ganho ou perdido depois de h pregoes, comparado com a carteira e com o CDI?"

Os dois benchmarks respondem perguntas diferentes:
  - CDI: valeu a pena sair da renda fixa?
  - carteira (media simples dos ativos monitorados, mesmas datas): a regra
    escolheu MELHOR do que pegar todos por igual, ou so pegou a alta geral?
    Substituiu o BOVA11 em 2026-09-26: e a comparacao certa para uma regra
    que escolhe dentro desse universo, e usa preco que ja e coletado.

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

Retorno com proventos (27/09/2026, Item 3): quando o chamador passa o mapa
de proventos do ativo (data-com -> valor por acao, de provento_distribuido),
o retorno soma o que foi distribuido no periodo ao preco de saida - sem
isso, pagadora de dividendo parece sistematicamente pior do que e. So cobre
dados a partir de 27/09/2026 (limite da fonte, ver app/validacao/proventos.py);
sinais mais antigos ficam sem ajuste por ausencia de dado, nao por erro.

O que NAO faz, de proposito: nao ajusta desdobramento/grupamento. Com preco
bruto (COTAHIST), um desdobramento aparece como queda de 50% sem ninguem ter
vendido; a janela que contem esse salto e marcada como suspeita e fica fora
das estatisticas, em vez de virar um "erro" da regra.
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
    retorno_carteira: Decimal | None
    retorno_cdi: Decimal | None
    excesso_carteira: Decimal | None
    ativos_na_carteira: int | None
    excesso_cdi: Decimal | None
    acerto: bool | None
    evento_suspeito: bool
    proventos_periodo: Decimal = Decimal("0")


# Abaixo disso a "media da carteira" e fina demais para representar o
# mercado; o excesso fica nulo em vez de comparar com 2 ou 3 papeis.
MINIMO_ATIVOS_CARTEIRA = 5


def avaliar(
    data_sinal: date,
    recomendacao: str | None,
    pregoes: list[Pregao],
    horizonte: int,
    carteira: dict[str, list[Pregao]] | None = None,
    cdi_diario: dict[date, Decimal] | None = None,
    custo_ida_e_volta: Decimal = CUSTO_IDA_E_VOLTA_PADRAO,
    proventos: dict[date, Decimal] | None = None,
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

    soma_proventos = _proventos_no_periodo(proventos, entrada.data, saida.data)
    retorno_bruto = (saida.fechamento + soma_proventos) / entrada.abertura - 1
    retorno_liquido = retorno_bruto - custo_ida_e_volta

    media_carteira, ativos_na_carteira = _media_da_carteira(carteira, entrada.data, saida.data)
    # Comprar a carteira inteira tambem paga custo: compara liquido com liquido.
    retorno_carteira = media_carteira - custo_ida_e_volta if media_carteira is not None else None
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
        retorno_carteira=_q(retorno_carteira),
        retorno_cdi=_q(retorno_cdi),
        excesso_carteira=_q(retorno_liquido - retorno_carteira) if retorno_carteira is not None else None,
        ativos_na_carteira=ativos_na_carteira,
        excesso_cdi=_q(retorno_liquido - retorno_cdi) if retorno_cdi is not None else None,
        acerto=acerto,
        evento_suspeito=_tem_salto_suspeito(serie[indice_sinal : indice_saida + 1]),
        proventos_periodo=_q(soma_proventos),
    )


def _media_da_carteira(
    carteira: dict[str, list[Pregao]] | None, data_entrada: date, data_saida: date
) -> tuple[Decimal | None, int | None]:
    """Media simples do retorno bruto dos ativos da carteira no periodo.

    Mesma convencao do sinal (abertura da entrada ao fechamento da saida).
    Entra so quem tem preco nas DUAS datas - comparar periodos diferentes nao
    e comparacao - e sem salto suspeito na janela: um desdobramento de outro
    papel nao pode contaminar a regua. Devolve (media, quantos entraram).
    """
    if not carteira:
        return None, None
    retornos = []
    for serie in carteira.values():
        janela = sorted(
            (p for p in serie if data_entrada <= p.data <= data_saida), key=lambda p: p.data
        )
        if not janela or janela[0].data != data_entrada or janela[-1].data != data_saida:
            continue
        if not janela[0].abertura or _tem_salto_suspeito(janela):
            continue
        retornos.append(janela[-1].fechamento / janela[0].abertura - 1)
    if len(retornos) < MINIMO_ATIVOS_CARTEIRA:
        return None, len(retornos)
    return sum(retornos) / len(retornos), len(retornos)


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


def _proventos_no_periodo(
    proventos: dict[date, Decimal] | None, data_entrada: date, data_saida: date
) -> Decimal:
    """Soma dos proventos com data-com em [entrada, saida) - mesma convencao
    de janela meio-aberta do CDI acumulado."""
    if not proventos:
        return Decimal("0")
    return sum((v for d, v in proventos.items() if data_entrada <= d < data_saida), Decimal("0"))


def _tem_salto_suspeito(janela: list[Pregao]) -> bool:
    for anterior, atual in zip(janela, janela[1:]):
        if anterior.fechamento and atual.abertura:
            salto = abs(atual.abertura / anterior.fechamento - 1)
            if salto >= LIMIAR_SALTO_SUSPEITO:
                return True
    return False


def _q(valor: Decimal | None) -> Decimal | None:
    return None if valor is None else valor.quantize(Decimal("0.000001"))
