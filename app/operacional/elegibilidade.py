"""Elegibilidade operacional (OPR-INS-1, DEC-OPR-1): o ativo pode entrar no paper trading neste pregao?

Puro: recebe as metricas de `ativo_liquidez_diaria` (ETL, OPR-ETL-1) e os fatos que o repositorio
levanta (fundamento vigente, evento corporativo e fato relevante recentes) e devolve a faixa de
liquidez e os bloqueios, cada um com motivo estruturado (codigo + detalhe + valor/limite) para o
painel e para o `evento_operacional`. Os limites vem de `regra_operacional.parametros_json`.

Faixas (SPEC "Parametros fixados"):
- MEDIA: passa nos quatro minimos (volume 63d, negocios 63d, presenca 63d, spread mediano);
- ALTA: o dobro de cada minimo (spread na metade do maximo);
- INSUFICIENTE: falha em algum minimo ou falta metrica de 63 pregoes.
Spread ausente nao reprova sozinho: o ativo cai uma faixa (ALTA -> MEDIA -> INSUFICIENTE).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

ALTA, MEDIA, INSUFICIENTE = "ALTA", "MEDIA", "INSUFICIENTE"

# Codigos de motivo (estaveis: o painel e os eventos dependem deles).
SEM_METRICA_LIQUIDEZ = "SEM_METRICA_LIQUIDEZ"
HISTORICO_INSUFICIENTE = "HISTORICO_INSUFICIENTE"
VOLUME_BAIXO = "VOLUME_BAIXO"
NEGOCIOS_BAIXOS = "NEGOCIOS_BAIXOS"
PRESENCA_BAIXA = "PRESENCA_BAIXA"
SPREAD_ALTO = "SPREAD_ALTO"
SPREAD_AUSENTE = "SPREAD_AUSENTE"  # ressalva: rebaixa a faixa, nao bloqueia por si
SEM_ATR = "SEM_ATR"
SERIE_SEM_AJUSTE = "SERIE_SEM_AJUSTE"
EVENTO_CORPORATIVO_RECENTE = "EVENTO_CORPORATIVO_RECENTE"
SEM_FUNDAMENTO_VIGENTE = "SEM_FUNDAMENTO_VIGENTE"
FATO_RELEVANTE_RECENTE = "FATO_RELEVANTE_RECENTE"

_REBAIXA = {ALTA: MEDIA, MEDIA: INSUFICIENTE, INSUFICIENTE: INSUFICIENTE}
_COLUNAS_63D = ("volume_financeiro_medio_63d", "negocios_medio_63d", "presenca_63d")


@dataclass(frozen=True)
class LimitesLiquidez:
    volume_minimo: Decimal
    negocios_minimo: Decimal
    presenca_minima: Decimal
    spread_maximo: Decimal
    fator_faixa_alta: Decimal = Decimal(2)
    fundamento_validade_dias: int = 460  # DFP anual + folga: sem entrega em ~15 meses, nao ha fundamento vigente
    dias_evento_recente: int = 5  # pregoes: fato relevante/evento nesse intervalo bloqueia a entrada

    @classmethod
    def de_parametros(cls, parametros: dict) -> LimitesLiquidez:
        """`regra_operacional.parametros_json` (V23). Campo ausente usa o padrao da DEC-OPR-1."""
        liq = parametros.get("liquidez") or {}
        ele = parametros.get("elegibilidade") or {}
        d = lambda chave, padrao: Decimal(str(liq.get(chave, padrao)))  # noqa: E731
        return cls(
            volume_minimo=d("volume_financeiro_medio_63d_min", 5_000_000),
            negocios_minimo=d("negocios_medio_63d_min", 500),
            presenca_minima=d("presenca_63d_min", "0.95"),
            spread_maximo=d("spread_mediano_63d_max", "0.005"),
            fator_faixa_alta=d("fator_faixa_alta", 2),
            fundamento_validade_dias=int(ele.get("fundamento_validade_dias", 460)),
            dias_evento_recente=int(ele.get("dias_evento_recente", 5)),
        )


@dataclass(frozen=True)
class Motivo:
    codigo: str
    detalhe: str
    valor: str | None = None
    limite: str | None = None


@dataclass(frozen=True)
class FatosDoAtivo:
    """O que o repositorio levanta alem da liquidez (tudo com data <= pregao da decisao)."""

    ultima_entrega_fundamento: date | None = None
    ultimo_evento_corporativo: date | None = None
    ultimo_fato_relevante: date | None = None
    pregoes_desde_evento: int | None = None
    pregoes_desde_fato: int | None = None


@dataclass
class Elegibilidade:
    simbolo: str
    data_pregao: date
    elegivel: bool
    faixa: str
    bloqueios: list[Motivo] = field(default_factory=list)
    ressalvas: list[Motivo] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)

    def como_json(self) -> dict:
        """Payload estruturado para o painel e para `operacao_simulada.motivo_entrada_json`."""
        return {
            "simbolo": self.simbolo, "data_pregao": self.data_pregao.isoformat(),
            "elegivel": self.elegivel, "faixa": self.faixa,
            "bloqueios": [asdict(m) for m in self.bloqueios],
            "ressalvas": [asdict(m) for m in self.ressalvas],
            "metricas": {k: (str(v) if v is not None else None) for k, v in self.metricas.items()},
        }


def _num(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def faixa_de_liquidez(metricas: dict | None, limites: LimitesLiquidez) -> tuple[str, list[Motivo], list[Motivo]]:
    """(faixa, motivos que reprovam, ressalvas)."""
    if not metricas:
        return INSUFICIENTE, [Motivo(SEM_METRICA_LIQUIDEZ, "sem linha em ativo_liquidez_diaria no pregão")], []
    faltando = [c for c in _COLUNAS_63D if metricas.get(c) is None]
    if faltando:
        return INSUFICIENTE, [Motivo(HISTORICO_INSUFICIENTE, "métricas de 63 pregões ausentes: " + ", ".join(faltando))], []

    volume, negocios = _num(metricas["volume_financeiro_medio_63d"]), _num(metricas["negocios_medio_63d"])
    presenca, spread = _num(metricas["presenca_63d"]), _num(metricas.get("spread_mediano_63d"))
    k = limites.fator_faixa_alta
    reprovas: list[Motivo] = []
    if volume < limites.volume_minimo:
        reprovas.append(Motivo(VOLUME_BAIXO, "volume financeiro médio de 63 pregões abaixo do mínimo",
                               str(volume), str(limites.volume_minimo)))
    if negocios < limites.negocios_minimo:
        reprovas.append(Motivo(NEGOCIOS_BAIXOS, "negócios médios de 63 pregões abaixo do mínimo",
                               str(negocios), str(limites.negocios_minimo)))
    if presenca < limites.presenca_minima:
        reprovas.append(Motivo(PRESENCA_BAIXA, "negociado em menos pregões que o mínimo",
                               str(presenca), str(limites.presenca_minima)))
    if spread is not None and spread > limites.spread_maximo:
        reprovas.append(Motivo(SPREAD_ALTO, "spread mediano acima do máximo", str(spread), str(limites.spread_maximo)))
    if reprovas:
        return INSUFICIENTE, reprovas, []

    alta = (volume >= limites.volume_minimo * k and negocios >= limites.negocios_minimo * k
            and presenca >= limites.presenca_minima
            and (spread is None or spread <= limites.spread_maximo / k))
    faixa = ALTA if alta else MEDIA
    ressalvas: list[Motivo] = []
    if spread is None:
        faixa = _REBAIXA[faixa]
        ressalvas.append(Motivo(SPREAD_AUSENTE, "sem ofertas suficientes para o spread: faixa rebaixada e custo conservador"))
        if faixa == INSUFICIENTE:
            return INSUFICIENTE, [Motivo(SPREAD_AUSENTE, "faixa MEDIA sem spread cai para INSUFICIENTE")], ressalvas
    return faixa, [], ressalvas


def avaliar(simbolo: str, data_pregao: date, metricas: dict | None, fatos: FatosDoAtivo,
            limites: LimitesLiquidez) -> Elegibilidade:
    """Elegivel = faixa ALTA ou MEDIA e nenhum bloqueio de serie, fundamento ou evento."""
    faixa, bloqueios, ressalvas = faixa_de_liquidez(metricas, limites)
    metricas = metricas or {}

    if metricas and metricas.get("atr14") is None:
        bloqueios.append(Motivo(SEM_ATR, "sem ATR de 14 pregões: não há como calcular stop nem tamanho"))
    if metricas.get("ajuste_serie") == "AJUSTE_INDISPONIVEL":
        bloqueios.append(Motivo(SERIE_SEM_AJUSTE, "série com salto sem ajuste conhecido (OPR-ETL-3)"))
    if (fatos.pregoes_desde_evento is not None and fatos.pregoes_desde_evento <= limites.dias_evento_recente
            and metricas.get("ajuste_serie", "BRUTA") == "BRUTA"):
        bloqueios.append(Motivo(EVENTO_CORPORATIVO_RECENTE,
                                "desdobramento/grupamento/bonificação recente com série bruta: ATR e stop distorcidos",
                                str(fatos.ultimo_evento_corporativo), f"{limites.dias_evento_recente} pregões"))
    if fatos.pregoes_desde_fato is not None and fatos.pregoes_desde_fato <= limites.dias_evento_recente:
        bloqueios.append(Motivo(FATO_RELEVANTE_RECENTE, "fato relevante na CVM nos últimos pregões",
                                str(fatos.ultimo_fato_relevante), f"{limites.dias_evento_recente} pregões"))
    entrega = fatos.ultima_entrega_fundamento
    if entrega is None or (data_pregao - entrega).days > limites.fundamento_validade_dias:
        bloqueios.append(Motivo(SEM_FUNDAMENTO_VIGENTE,
                                "nenhum fundamento entregue à CVM até o pregão dentro da validade",
                                str(entrega) if entrega else None, f"{limites.fundamento_validade_dias} dias"))

    elegivel = faixa in (ALTA, MEDIA) and not bloqueios
    return Elegibilidade(simbolo, data_pregao, elegivel, faixa, bloqueios, ressalvas, dict(metricas))
