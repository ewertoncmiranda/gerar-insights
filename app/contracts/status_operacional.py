# Gerado por infra/scripts/sincronizar-contratos.mjs (contracts/operacional/status-sistema.v1).
from enum import StrEnum


class StatusOperacional(StrEnum):
    NAO_OPERAVEL = "NAO_OPERAVEL"
    EM_OBSERVACAO = "EM_OBSERVACAO"
    PAPER_TRADING_ELEGIVEL = "PAPER_TRADING_ELEGIVEL"
    BLOQUEADO = "BLOQUEADO"
