"""Custos simulados por lado da operacao (base do OPR-INS-5; o IR estimado entra la).

custo = valor x (custo_fixo_bps / 10000 + spread / 2). Spread usado (combinado com o ETL, OPR-ETL-2):
1. `spread_mediano_63d` (ofertas cotadas) quando existe — nunca substituido pelo estimado, que em
   ativo liquido superestima muito (PETR4: 0,63% estimado contra 0,04% cotado);
2. sem cotado: max(`spread_estimado_63d` (Corwin-Schultz, V24), `spread_mediano_63d_max` da regra);
3. sem os dois: `spread_mediano_63d_max` (reserva conservadora).
"""

from __future__ import annotations

from decimal import Decimal


def spread_para_custo(spread_cotado: Decimal | None, spread_estimado: Decimal | None, parametros: dict) -> Decimal:
    reserva = Decimal(str((parametros.get("liquidez") or {}).get("spread_mediano_63d_max", "0.005")))
    if spread_cotado is not None:
        return spread_cotado
    if spread_estimado is not None:
        return max(spread_estimado, reserva)
    return reserva


def custo_por_lado(valor: Decimal, spread: Decimal | None, parametros: dict,
                   spread_estimado: Decimal | None = None) -> Decimal:
    custo_fixo = Decimal(str((parametros.get("custos") or {}).get("custo_fixo_bps", 10))) / Decimal(10000)
    meio_spread = spread_para_custo(spread, spread_estimado, parametros) / 2
    return (abs(valor) * (custo_fixo + meio_spread)).quantize(Decimal("0.01"))