"""Fatores de evento a partir dos comunicados da CVM (LAC-INS-6). Puro.

Conta por DATA DE ENTREGA, nunca pela data de referencia: ha 36 datas de
referencia invalidas no IPE, e so a entrega diz quando o mercado soube.
"""

from __future__ import annotations

from datetime import date, timedelta

# codigo do fator -> (categorias de comunicado_cvm, janela em dias corridos)
EVENTOS = {
    "FATOS_RELEVANTES_90D": (frozenset({"FATO_RELEVANTE"}), 90),
    "AVISOS_PROVENTOS_180D": (frozenset({"PROVENTOS"}), 180),
}


def calcular(comunicados: list[tuple[str, date]], referencia: date) -> dict[str, float]:
    """comunicados: (categoria, data_entrega) do emissor. Janela [ref - N, ref):
    o que foi entregue no proprio dia de referencia ainda nao conta."""
    fatores = {}
    for codigo, (categorias, dias) in EVENTOS.items():
        inicio = referencia - timedelta(days=dias)
        fatores[codigo] = float(sum(1 for cat, entrega in comunicados
                                    if cat in categorias and inicio <= entrega < referencia))
    return fatores
