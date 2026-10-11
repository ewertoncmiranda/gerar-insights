"""Trava de operabilidade (OPR-INS-6, DEC-OPR-1).

Puro: recebe os agregados do diario e devolve o status do sistema.
Nao faz acesso ao banco — o diario.py consulta o que for necessario e passa.

Progressao de estados:
  NAO_OPERAVEL          -> sem entradas no diario (estado inicial do DB)
  EM_OBSERVACAO         -> coletando dados; criterios ainda nao cumpridos
  PAPER_TRADING_ELEGIVEL-> todos os criterios cumpridos (paper trading apenas)
  BLOQUEADO             -> drawdown ultrapassou o limite duro

"PAPER_TRADING_ELEGIVEL" nao e recomendacao de uso com capital real.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

NAO_OPERAVEL = "NAO_OPERAVEL"
EM_OBSERVACAO = "EM_OBSERVACAO"
PAPER_TRADING_ELEGIVEL = "PAPER_TRADING_ELEGIVEL"
BLOQUEADO = "BLOQUEADO"


@dataclass(frozen=True)
class ParametrosTrava:
    min_pregoes: int              # janela minima para sair de EM_OBSERVACAO
    min_operacoes_encerradas: int  # amostra minima de operacoes fechadas
    drawdown_max_elegivel: Decimal  # drawdown maximo permitido para ELEGIVEL (< 0, ex.: -0.15)
    drawdown_max_bloqueio: Decimal  # limite duro: abaixo disso vira BLOQUEADO (< 0, ex.: -0.25)

    @classmethod
    def de_parametros(cls, parametros: dict) -> ParametrosTrava:
        """Le de regra_operacional.parametros_json['trava']. Campo ausente usa DEC-OPR-1."""
        t = parametros.get("trava") or {}
        d = lambda k, v: Decimal(str(t.get(k, v)))  # noqa: E731
        return cls(
            min_pregoes=int(t.get("min_pregoes", 63)),
            min_operacoes_encerradas=int(t.get("min_operacoes_encerradas", 10)),
            drawdown_max_elegivel=d("drawdown_max_elegivel", "-0.15"),
            drawdown_max_bloqueio=d("drawdown_max_bloqueio", "-0.25"),
        )


@dataclass(frozen=True)
class ResultadoStatus:
    status: str                           # um dos quatro estados acima
    criterios_nao_atendidos: list[str]    # lista de motivos legíveis; vazia quando elegivel
    pregoes_avaliados: int                # quantos pregoes o diario tem nesta versao_regra


def calcular(
    *,
    pregoes_no_diario: int,
    retorno_liquido_acumulado: Decimal,
    cdi_liquido_ir_acumulado: Decimal,
    drawdown_maximo: Decimal,          # valor mais negativo do diario; 0 se nunca houve DD
    violacoes_liquidez_total: int,     # soma de violacoes_liquidez em todo o diario
    operacoes_encerradas: int,
    parametros: ParametrosTrava,
) -> ResultadoStatus:
    """Calcula o status_sistema para o pregao corrente.

    Chamado ao final de cada pregao pelo DiarioOperacional._pregao.
    Recebe os valores ja computados para o pregao (acumulados desde o inicio
    da versao_regra); nao consulta o banco.
    """
    if pregoes_no_diario == 0:
        return ResultadoStatus(NAO_OPERAVEL, ["sem_pregoes_no_diario"], 0)

    # Limite duro: BLOQUEADO tem prioridade sobre qualquer outro criterio.
    if drawdown_maximo < parametros.drawdown_max_bloqueio:
        return ResultadoStatus(
            BLOQUEADO,
            [f"drawdown_maximo={drawdown_maximo:.4f} < limite={parametros.drawdown_max_bloqueio}"],
            pregoes_no_diario,
        )

    # Acumular criterios nao atendidos para EM_OBSERVACAO.
    pendentes: list[str] = []

    if pregoes_no_diario < parametros.min_pregoes:
        pendentes.append(f"pregoes={pregoes_no_diario}/{parametros.min_pregoes}")

    if operacoes_encerradas < parametros.min_operacoes_encerradas:
        pendentes.append(f"operacoes_encerradas={operacoes_encerradas}/{parametros.min_operacoes_encerradas}")

    if retorno_liquido_acumulado <= cdi_liquido_ir_acumulado:
        pendentes.append(
            f"retorno_liq={retorno_liquido_acumulado:.6f} <= cdi_liq={cdi_liquido_ir_acumulado:.6f}"
        )

    if drawdown_maximo < parametros.drawdown_max_elegivel:
        pendentes.append(
            f"drawdown_maximo={drawdown_maximo:.4f} < limite_elegivel={parametros.drawdown_max_elegivel}"
        )

    if violacoes_liquidez_total > 0:
        pendentes.append(f"violacoes_liquidez={violacoes_liquidez_total}")

    if not pendentes:
        return ResultadoStatus(PAPER_TRADING_ELEGIVEL, [], pregoes_no_diario)

    return ResultadoStatus(EM_OBSERVACAO, pendentes, pregoes_no_diario)
