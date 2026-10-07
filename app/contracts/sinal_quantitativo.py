"""Nomenclatura pública dos sinais quantitativos (DEC-05 / TASK-55).

Os nomes antigos continuam aceitos na leitura de histórico, mas nenhum insight
novo deve expor linguagem de compra ou venda.
"""
from enum import StrEnum


class SinalQuantitativo(StrEnum):
    SINAL_POSITIVO_FORTE = "SINAL_POSITIVO_FORTE"
    SINAL_POSITIVO = "SINAL_POSITIVO"
    SEM_MARGEM = "SEM_MARGEM"
    ALERTA_RISCO = "ALERTA_RISCO"
    NEUTRO = "NEUTRO"
    SEM_DADOS = "SEM_DADOS"


_LEGADO_PARA_SINAL = {
    "COMPRA_FORTE": SinalQuantitativo.SINAL_POSITIVO_FORTE,
    "COMPRA_MODERADA": SinalQuantitativo.SINAL_POSITIVO,
    "VENDA_VALUATION": SinalQuantitativo.SEM_MARGEM,
    "MANTER": SinalQuantitativo.NEUTRO,
    "ALERTA_RISCO": SinalQuantitativo.ALERTA_RISCO,
    "SEM_DADOS": SinalQuantitativo.SEM_DADOS,
}


def como_sinal_quantitativo(valor: str | SinalQuantitativo) -> str:
    """Converte a classificação interna/legada para o contrato público v3."""
    if isinstance(valor, SinalQuantitativo):
        return valor.value
    try:
        return SinalQuantitativo(valor).value
    except ValueError:
        try:
            return _LEGADO_PARA_SINAL[valor].value
        except KeyError as erro:
            raise ValueError(f"Classificacao de sinal desconhecida: {valor}") from erro
