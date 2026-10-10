"""Custos simulados por lado da operacao (base do OPR-INS-5; o IR estimado entra la).

custo = valor x (custo_fixo_bps / 10000 + spread / 2). Spread ausente usa o maximo aceito pela regra
de liquidez (reserva conservadora: custo maior para o ativo sem ofertas suficientes).
"""

from __future__ import annotations

from decimal import Decimal


def custo_por_lado(valor: Decimal, spread: Decimal | None, parametros: dict) -> Decimal:
    custo_fixo = Decimal(str((parametros.get("custos") or {}).get("custo_fixo_bps", 10))) / Decimal(10000)
    reserva = Decimal(str((parametros.get("liquidez") or {}).get("spread_mediano_63d_max", "0.005")))
    meio_spread = (spread if spread is not None else reserva) / 2
    return (abs(valor) * (custo_fixo + meio_spread)).quantize(Decimal("0.01"))
