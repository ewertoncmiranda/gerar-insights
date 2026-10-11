"""Consenso de sinais da Operabilidade V2 (OPRV2-INS-2).

Puro: separa sinal analitico de operabilidade. Um ativo pode ter sinal
analitico positivo e, ao mesmo tempo, estar bloqueado por liquidez/dado.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POSITIVOS = {"COMPRA_FORTE", "COMPRA_MODERADA", "COMPRA_TECNICA", "SINAL_POSITIVO"}
NEGATIVOS = {"VENDA_VALUATION", "VENDA_TECNICA", "SINAL_NEGATIVO", "ALERTA_RISCO"}
NEUTROS = {"MANTER", "SEM_MARGEM", "NEUTRO_TECNICO", "SEM_BASE", "SEM_DADOS"}
OPERAVEIS = {"PAPER_TRADING_ELEGIVEL", "EM_OBSERVACAO"}


@dataclass(frozen=True)
class SinalConsenso:
    fonte: str
    valor: str | None
    direcao: str
    peso: int = 1
    detalhe: str | None = None

    def como_dict(self) -> dict:
        return {
            "fonte": self.fonte,
            "valor": self.valor,
            "direcao": self.direcao,
            "peso": self.peso,
            "detalhe": self.detalhe,
        }


@dataclass(frozen=True)
class ConsensoSinais:
    direcao_analitica: str
    operabilidade: str
    resumo: str
    sinais: list[SinalConsenso] = field(default_factory=list)
    divergencias: list[dict] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "direcaoAnalitica": self.direcao_analitica,
            "operabilidade": self.operabilidade,
            "resumo": self.resumo,
            "sinais": [s.como_dict() for s in self.sinais],
            "divergencias": self.divergencias,
        }


def direcao(valor: str | None) -> str:
    if valor is None:
        return "AUSENTE"
    if valor in POSITIVOS:
        return "POSITIVO"
    if valor in NEGATIVOS:
        return "NEGATIVO"
    if valor in NEUTROS:
        return "NEUTRO"
    return "DESCONHECIDO"


def montar_consenso(
    *,
    sinal_principal: str | None,
    sinal_momentum: str | None = None,
    sinal_reversao: str | None = None,
    sinal_v2: str | None = None,
    opiniao_ia: str | None = None,
    status_operacional: str | None = None,
    motivos_bloqueio: list[dict] | None = None,
) -> ConsensoSinais:
    sinais = [
        SinalConsenso("REGRA_PRINCIPAL", sinal_principal, direcao(sinal_principal), peso=3),
        SinalConsenso("TECNICO_MOMENTUM", sinal_momentum, direcao(sinal_momentum)),
        SinalConsenso("TECNICO_REVERSAO", sinal_reversao, direcao(sinal_reversao)),
        SinalConsenso("REGRA_V2_SOMBRA", sinal_v2, direcao(sinal_v2), detalhe="modo sombra"),
        SinalConsenso("OPINIAO_IA", opiniao_ia, direcao(opiniao_ia)),
    ]
    pontuacao = {"POSITIVO": 0, "NEGATIVO": 0, "NEUTRO": 0}
    for s in sinais:
        if s.direcao in pontuacao:
            pontuacao[s.direcao] += s.peso

    if pontuacao["POSITIVO"] > pontuacao["NEGATIVO"] and pontuacao["POSITIVO"] > pontuacao["NEUTRO"]:
        analitica = "POSITIVA"
    elif pontuacao["NEGATIVO"] > pontuacao["POSITIVO"] and pontuacao["NEGATIVO"] > pontuacao["NEUTRO"]:
        analitica = "NEGATIVA"
    else:
        analitica = "NEUTRA_OU_MISTA"

    bloqueios = motivos_bloqueio or []
    operabilidade = "OPERAVEL" if status_operacional in OPERAVEIS and not bloqueios else "NAO_OPERAVEL"
    divergencias = []
    if analitica == "POSITIVA" and operabilidade == "NAO_OPERAVEL":
        divergencias.append({
            "codigo": "SINAL_POSITIVO_NAO_OPERAVEL",
            "descricao": "Sinal analitico positivo, mas a operabilidade esta bloqueada ou sem evidencia suficiente.",
            "motivos": bloqueios,
        })
    if sinal_momentum and sinal_reversao and direcao(sinal_momentum) != direcao(sinal_reversao):
        divergencias.append({
            "codigo": "TECNICOS_DIVERGENTES",
            "descricao": "Momentum e reversao apontam direcoes diferentes.",
        })

    return ConsensoSinais(
        direcao_analitica=analitica,
        operabilidade=operabilidade,
        resumo=_resumo(analitica, operabilidade, divergencias),
        sinais=sinais,
        divergencias=divergencias,
    )


def _resumo(analitica: str, operabilidade: str, divergencias: list[dict]) -> str:
    if divergencias:
        return "Ha divergencia entre qualidade do sinal e condicao operacional."
    if analitica == "POSITIVA" and operabilidade == "OPERAVEL":
        return "Sinais majoritariamente positivos e ativo operacionalmente apto em simulacao."
    if analitica == "NEGATIVA":
        return "Sinais majoritariamente negativos; nao promover operacao simulada."
    return "Sinais mistos ou neutros; manter leitura conservadora."
