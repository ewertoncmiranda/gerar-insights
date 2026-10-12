"""Trava decisoria para cadeia de opcoes (OPT-INS-1).

O worker nao usa opcoes para sinal, tese, confianca, backtest, sizing ou
operacao simulada enquanto a saude da cadeia nao provar que existe base valida.
Quando a cadeia nao estiver apta, o unico uso permitido e pedagogico/risco:
``CADEIA_OPCOES_NAO_VALIDADA``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

CADEIA_OPCOES_NAO_VALIDADA = "CADEIA_OPCOES_NAO_VALIDADA"
CADEIA_OPCOES_VALIDADA = "CADEIA_OPCOES_VALIDADA"


@dataclass(frozen=True)
class ResultadoUsoOpcoes:
    """Resultado puro, sem acesso a banco/API, para decidir se opcoes podem entrar no motor."""

    permitido: bool
    codigo: str
    motivos: list[str]


def avaliar_uso_decisorio(saude_opcoes: dict[str, Any] | None) -> ResultadoUsoOpcoes:
    """Avalia se a cadeia de opcoes pode ser usada de forma decisoria.

    A entrada esperada e o contrato de saude vindo do gestor/infra. Ausencia,
    legado nao validado, ausencia de registros validos ou percentual nulo/zero
    bloqueiam o uso. A funcao e intencionalmente conservadora.
    """
    if not saude_opcoes:
        return ResultadoUsoOpcoes(
            permitido=False,
            codigo=CADEIA_OPCOES_NAO_VALIDADA,
            motivos=["saude_opcoes_ausente"],
        )

    motivos: list[str] = []
    status = str(saude_opcoes.get("status") or "").upper()
    registros_validos = _inteiro(saude_opcoes.get("registrosValidos", saude_opcoes.get("registros_validos")))
    legado_nao_validado = _inteiro(
        saude_opcoes.get("registrosLegadoNaoValidado", saude_opcoes.get("registros_legado_nao_validado"))
    )
    percentual_valido = _decimal(saude_opcoes.get("percentualValido", saude_opcoes.get("percentual_valido")))

    if status and status not in {"OK", "CADEIA_VALIDADA"}:
        motivos.append(f"status={status}")

    if registros_validos <= 0:
        motivos.append("sem_registros_validos")

    if legado_nao_validado > 0:
        motivos.append(f"legado_nao_validado={legado_nao_validado}")

    if percentual_valido <= Decimal("0"):
        motivos.append(f"percentual_valido={percentual_valido}")

    if motivos:
        return ResultadoUsoOpcoes(False, CADEIA_OPCOES_NAO_VALIDADA, motivos)

    return ResultadoUsoOpcoes(True, CADEIA_OPCOES_VALIDADA, [])


def _inteiro(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
