"""Regra de saida (OPR-INS-3, DEC-OPR-1): a posicao simulada aberta deve sair neste pregao?

Puro: recebe a posicao (estado de `operacao_simulada`), o que se sabe no fechamento do pregao D e
os parametros de `regra_operacional.parametros_json["saida"|"liquidez"]`, e devolve o estado
atualizado (maxima desde a entrada, stop atual, trailing armado) e, se houver, a decisao de saida.

Decisao no fechamento de D, execucao simulada na ABERTURA de D+1 (o diario, OPR-INS-4, preenche
`data_saida`/`preco_saida` com o pregao seguinte; nunca o fechamento de D, que seria olhar o futuro).

Motivos (SPEC "Parametros fixados"; prioridade configuravel em `saida.prioridade`):
1. EVENTO   fato relevante na CVM desde a entrada, ou salto de preco sem evento que o explique
            (`ajuste_serie = AJUSTE_INDISPONIVEL`, OPR-ETL-3);
2. STOP     fechamento abaixo do stop: entrada - stop_atr x ATR; depois de +trailing_armado_apos_atr x ATR
            de ganho (pela maxima), stop movel = maxima desde a entrada - trailing_atr x ATR, que so sobe;
3. LIQUIDEZ dias_iliquido_saida pregoes seguidos na faixa INSUFICIENTE;
4. SINAL    opiniao do horizonte da operacao vira SINAL_NEGATIVO ou SEM_BASE;
5. PRAZO    pregoes em posicao (o da entrada conta como 1) >= horizonte da tese.
Mais de um motivo no mesmo pregao: vale o primeiro da prioridade; os demais ficam no detalhe.

O ATR usado nos stops e o da ENTRADA (`atr_entrada`): a distancia do stop fica fixa durante a
operacao, sem encolher quando a volatilidade cai nem ser distorcida por evento corporativo no meio.
Dado ausente (opiniao, contagem de iliquidez) nunca dispara saida: vira ressalva.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal

EVENTO, STOP, LIQUIDEZ, SINAL, PRAZO = "EVENTO", "STOP", "LIQUIDEZ", "SINAL", "PRAZO"
PRIORIDADE_PADRAO = (EVENTO, STOP, LIQUIDEZ, SINAL, PRAZO)

# Codigos de motivo (estaveis: o painel, `motivo_saida_json` e o evento posicao-fechada dependem deles).
FATO_RELEVANTE = "FATO_RELEVANTE"
SALTO_SEM_EVENTO = "SALTO_SEM_EVENTO"
STOP_INICIAL = "STOP_INICIAL"
STOP_MOVEL = "STOP_MOVEL"
ILIQUIDEZ_PROLONGADA = "ILIQUIDEZ_PROLONGADA"
SINAL_VIROU = "SINAL_VIROU"
PRAZO_DA_TESE = "PRAZO_DA_TESE"
SEM_OPINIAO = "SEM_OPINIAO"  # ressalva
SEM_CONTAGEM_LIQUIDEZ = "SEM_CONTAGEM_LIQUIDEZ"  # ressalva

SINAIS_DE_SAIDA = ("SINAL_NEGATIVO", "SEM_BASE")
EXECUCAO = "ABERTURA_D_MAIS_1"


class PosicaoNaoAberta(ValueError):
    """Operacao ainda PENDENTE (sem entrada executada) ou ja fechada: nao ha o que avaliar."""


@dataclass(frozen=True)
class ParametrosSaida:
    stop_atr: Decimal = Decimal(2)
    trailing_atr: Decimal = Decimal(3)
    trailing_armado_apos_atr: Decimal = Decimal(1)
    dias_iliquido_saida: int = 5
    prioridade: tuple[str, ...] = PRIORIDADE_PADRAO

    @classmethod
    def de_parametros(cls, parametros: dict) -> ParametrosSaida:
        """`regra_operacional.parametros_json` (V23). Campo ausente usa o padrao da DEC-OPR-1."""
        saida = parametros.get("saida") or {}
        liq = parametros.get("liquidez") or {}
        d = lambda chave, padrao: Decimal(str(saida.get(chave, padrao)))  # noqa: E731
        prioridade = tuple(saida.get("prioridade") or PRIORIDADE_PADRAO)
        desconhecidos = set(prioridade) - set(PRIORIDADE_PADRAO)
        if desconhecidos or len(set(prioridade)) != len(PRIORIDADE_PADRAO):
            raise ValueError(f"saida.prioridade precisa ter os 5 motivos sem repetir: {list(prioridade)}")
        return cls(stop_atr=d("stop_atr", 2), trailing_atr=d("trailing_atr", 3),
                   trailing_armado_apos_atr=d("trailing_armado_apos_atr", 1),
                   dias_iliquido_saida=int(liq.get("dias_iliquido_saida", 5)), prioridade=prioridade)


@dataclass(frozen=True)
class Posicao:
    """O que importa de `operacao_simulada` para a saida (status ABERTA)."""

    simbolo: str
    horizonte_pregoes: int
    data_entrada: date | None
    preco_entrada: Decimal | None
    atr_entrada: Decimal | None
    stop_atual: Decimal | None = None
    maxima_desde_entrada: Decimal | None = None


@dataclass(frozen=True)
class PregaoDaPosicao:
    """O que se sabe no fechamento do pregao D sobre o ativo (tudo com data <= D).

    `pregoes_em_posicao`: pregoes de `data_entrada` a D, inclusive (o da entrada conta como 1).
    `fatos_relevantes`: datas de fato relevante (IPE) do emissor; so contam as >= data_entrada.
    `dias_insuficiente_seguidos`: pregoes seguidos ate D na faixa INSUFICIENTE (None = sem historico).
    `opiniao`: opiniao do horizonte da operacao em D (`opiniao_ia`), None se nao gravada.
    """

    data_pregao: date
    fechamento: Decimal
    maxima: Decimal
    pregoes_em_posicao: int
    fatos_relevantes: tuple[date, ...] = ()
    ajuste_serie: str = "BRUTA"
    dias_insuficiente_seguidos: int | None = 0
    opiniao: str | None = None


@dataclass(frozen=True)
class Motivo:
    codigo: str
    detalhe: str
    valor: str | None = None
    limite: str | None = None


@dataclass
class AvaliacaoSaida:
    posicao: Posicao                       # estado atualizado (maxima, stop) para gravar mesmo sem saida
    trailing_armado: bool
    motivo_saida: str | None = None        # EVENTO | STOP | LIQUIDEZ | SINAL | PRAZO, ou None (fica)
    gatilhos: dict[str, list[Motivo]] = field(default_factory=dict)  # todos os que dispararam
    ressalvas: list[Motivo] = field(default_factory=list)
    data_decisao: date | None = None

    @property
    def sai(self) -> bool:
        return self.motivo_saida is not None

    def motivo_saida_json(self) -> dict:
        """Payload de `operacao_simulada.motivo_saida_json` e de `motivo_saida_detalhe` (posicao-fechada.v1)."""
        p = self.posicao
        return {
            "motivo": self.motivo_saida,
            "data_decisao": self.data_decisao.isoformat() if self.data_decisao else None,
            "execucao": EXECUCAO,
            "gatilhos": {m: [asdict(x) for x in lista] for m, lista in self.gatilhos.items()},
            "ressalvas": [asdict(x) for x in self.ressalvas],
            "stop_atual": _txt(p.stop_atual), "maxima_desde_entrada": _txt(p.maxima_desde_entrada),
            "trailing_armado": self.trailing_armado,
        }


def _txt(valor: Decimal | None) -> str | None:
    return None if valor is None else str(valor)


def _q(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.000001"))


def stop_inicial(preco_entrada: Decimal, atr_entrada: Decimal, parametros: ParametrosSaida) -> Decimal:
    """Stop no momento da entrada: entrada - stop_atr x ATR (o sizing, OPR-INS-2, usa o mesmo valor)."""
    return _q(preco_entrada - parametros.stop_atr * atr_entrada)


def avaliar(posicao: Posicao, pregao: PregaoDaPosicao, parametros: ParametrosSaida) -> AvaliacaoSaida:
    """Atualiza maxima/stop com o pregao D e decide se a posicao sai na abertura de D+1."""
    if posicao.data_entrada is None or posicao.preco_entrada is None or posicao.atr_entrada is None:
        raise PosicaoNaoAberta(f"{posicao.simbolo}: entrada ainda nao executada")
    if pregao.data_pregao < posicao.data_entrada:
        raise ValueError(f"{posicao.simbolo}: pregao {pregao.data_pregao} anterior a entrada {posicao.data_entrada}")

    entrada, atr = Decimal(posicao.preco_entrada), Decimal(posicao.atr_entrada)
    maxima = max(Decimal(pregao.maxima), Decimal(posicao.maxima_desde_entrada or entrada))
    inicial = stop_inicial(entrada, atr, parametros)
    armado = maxima >= entrada + parametros.trailing_armado_apos_atr * atr
    stop = max(inicial, Decimal(posicao.stop_atual or inicial))  # o stop so sobe
    if armado:
        stop = max(stop, _q(maxima - parametros.trailing_atr * atr))
    atualizada = replace(posicao, maxima_desde_entrada=maxima, stop_atual=stop)

    gatilhos: dict[str, list[Motivo]] = {}
    ressalvas: list[Motivo] = []

    fatos = sorted(d for d in pregao.fatos_relevantes if posicao.data_entrada <= d <= pregao.data_pregao)
    if fatos:
        gatilhos.setdefault(EVENTO, []).append(
            Motivo(FATO_RELEVANTE, "fato relevante na CVM desde a entrada", fatos[-1].isoformat()))
    if pregao.ajuste_serie == "AJUSTE_INDISPONIVEL":
        gatilhos.setdefault(EVENTO, []).append(
            Motivo(SALTO_SEM_EVENTO, "salto de preço sem evento corporativo que o explique (OPR-ETL-3)"))

    fechamento = Decimal(pregao.fechamento)
    if fechamento < stop:
        movel = armado and stop > inicial
        gatilhos[STOP] = [Motivo(STOP_MOVEL if movel else STOP_INICIAL,
                                 "fechamento abaixo do stop móvel" if movel else "fechamento abaixo do stop inicial",
                                 str(fechamento), str(stop))]

    if pregao.dias_insuficiente_seguidos is None:
        ressalvas.append(Motivo(SEM_CONTAGEM_LIQUIDEZ, "sem histórico de faixa de liquidez para contar os pregões"))
    elif pregao.dias_insuficiente_seguidos >= parametros.dias_iliquido_saida:
        gatilhos[LIQUIDEZ] = [Motivo(ILIQUIDEZ_PROLONGADA, "pregões seguidos na faixa INSUFICIENTE",
                                     str(pregao.dias_insuficiente_seguidos), str(parametros.dias_iliquido_saida))]

    if pregao.opiniao is None:
        ressalvas.append(Motivo(SEM_OPINIAO, f"sem opinião gravada para o horizonte de {posicao.horizonte_pregoes} pregões"))
    elif pregao.opiniao in SINAIS_DE_SAIDA:
        gatilhos[SINAL] = [Motivo(SINAL_VIROU, "opinião do horizonte da operação deixou de sustentar a tese",
                                  pregao.opiniao)]

    if pregao.pregoes_em_posicao >= posicao.horizonte_pregoes:
        gatilhos[PRAZO] = [Motivo(PRAZO_DA_TESE, "fim do horizonte da tese",
                                  str(pregao.pregoes_em_posicao), str(posicao.horizonte_pregoes))]

    motivo = next((m for m in parametros.prioridade if m in gatilhos), None)
    return AvaliacaoSaida(atualizada, armado, motivo, gatilhos, ressalvas,
                          pregao.data_pregao if motivo else None)
