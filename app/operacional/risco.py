"""Sizing teorico (OPR-INS-2, DEC-OPR-1): quantas acoes comprar numa entrada?

Puro: recebe capital, caixa disponivel, posicoes abertas por setor, metricas de
liquidez e elegibilidade, e devolve a quantidade e o motivo caso a posicao seja
bloqueada antes de abrir.

Fluxo (numeros da SPEC "Tamanho de posicao"):
  1. quantidade_risco = (capital * risco_por_operacao) / (stop_atr * atr14)
  2. Limites (menor valor):
       max_ativo   = exposicao_max_ativo * capital / preco
       max_setor   = espaco_restante_setor / preco
       max_adtv    = max_participacao_adtv * vol21d / preco
       max_caixa   = caixa / preco
       (max_posicoes e verificado antes: retorna LIMITE_POSICOES_ABERTAS)
  3. Redutores multiplicativos:
       faixa MEDIA          => * redutor_liquidez_media
       volatilidade > p80   => * redutor_vol_p80
  4. Arredonda para baixo em lotes de 100 (inteiro); fracionario fica separado.
     Valor final < posicao_minima => nao abre (POSICAO_ABAIXO_DO_MINIMO).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from app.operacional.elegibilidade import ALTA, MEDIA

# Codigos de motivo de bloqueio (estaveis).
SEM_ATR_SIZING = "SEM_ATR_SIZING"
LIMITE_POSICOES_ABERTAS = "LIMITE_POSICOES_ABERTAS"
POSICAO_ABAIXO_DO_MINIMO = "POSICAO_ABAIXO_DO_MINIMO"
CAIXA_INSUFICIENTE = "CAIXA_INSUFICIENTE"


@dataclass(frozen=True)
class LimitesSizing:
    risco_por_operacao: Decimal       # 0.005 = 0,5% do capital
    stop_atr: Decimal                 # 2 (multiplo do ATR14 para o stop inicial)
    exposicao_max_ativo: Decimal      # 0.05 = 5% do capital
    exposicao_max_setor: Decimal      # 0.20 = 20% do capital
    max_participacao_adtv: Decimal    # 0.01 = 1% do volume financeiro medio 21d
    max_posicoes: int                 # 15
    posicao_minima: Decimal           # 500 R$
    redutor_liquidez_media: Decimal   # 0.5
    redutor_vol_p80: Decimal          # 0.75

    @classmethod
    def de_parametros(cls, parametros: dict) -> LimitesSizing:
        """Leitura de `regra_operacional.parametros_json`. Ausente usa os padroes DEC-OPR-1."""
        s = parametros.get("sizing") or {}
        d = lambda chave, pad: Decimal(str(s.get(chave, pad)))  # noqa: E731
        return cls(
            risco_por_operacao=d("risco_por_operacao", "0.005"),
            stop_atr=d("stop_atr", 2),
            exposicao_max_ativo=d("exposicao_max_ativo", "0.05"),
            exposicao_max_setor=d("exposicao_max_setor", "0.20"),
            max_participacao_adtv=d("max_participacao_adtv", "0.01"),
            max_posicoes=int(s.get("max_posicoes", 15)),
            posicao_minima=d("posicao_minima", 500),
            redutor_liquidez_media=d("redutor_liquidez_media", "0.5"),
            redutor_vol_p80=d("redutor_vol_p80", "0.75"),
        )


@dataclass(frozen=True)
class ResultadoSizing:
    elegivel: bool                  # False = nao abre a posicao
    motivo_bloqueio: str | None     # codigo estavel quando elegivel=False
    detalhe: str | None             # texto legivel para o painel
    quantidade_inteira: int         # lote de 100; 0 quando bloqueado
    quantidade_fracionaria: int     # resto (0-99); 0 quando bloqueado
    valor_financeiro: Decimal       # quantidade total * preco; 0 quando bloqueado
    redutores_aplicados: list[str]  # lista de codigos aplicados


def calcular(
    *,
    capital: Decimal,
    caixa: Decimal,
    preco: Decimal,
    atr14: Decimal | None,
    faixa: str,
    percentil_volatilidade: Decimal | None,
    vol21d: Decimal | None,
    exposicao_atual_ativo: Decimal,
    exposicao_atual_setor: Decimal,
    posicoes_abertas: int,
    limites: LimitesSizing,
) -> ResultadoSizing:
    """Retorna o sizing teorico para uma nova entrada.

    Args:
        capital: capital teorico total (ex.: 100_000)
        caixa: caixa disponivel (capital - exposicao aberta)
        preco: preco de fechamento do pregao D (entrada simulada na abertura D+1)
        atr14: ATR de 14 pregoes da `ativo_liquidez_diaria`
        faixa: ALTA, MEDIA ou INSUFICIENTE (elegibilidade.py)
        percentil_volatilidade: percentil da volatilidade 63d no universo (0-1)
        vol21d: volume financeiro medio de 21 pregoes
        exposicao_atual_ativo: valor ja alocado neste ativo
        exposicao_atual_setor: valor ja alocado no setor do ativo
        posicoes_abertas: numero de posicoes simuladas abertas agora
        limites: LimitesSizing lidos de regra_operacional
    """
    _zero = Decimal(0)

    # --- pre-verificacoes ---
    if atr14 is None or atr14 <= _zero:
        return ResultadoSizing(False, SEM_ATR_SIZING, "ATR14 ausente: nao e possivel calcular o stop",
                               0, 0, _zero, [])

    if posicoes_abertas >= limites.max_posicoes:
        return ResultadoSizing(False, LIMITE_POSICOES_ABERTAS,
                               f"limite de {limites.max_posicoes} posicoes simultaneas atingido",
                               0, 0, _zero, [])

    # --- 1. quantidade pelo risco ---
    valor_risco = capital * limites.risco_por_operacao
    stop_reais = limites.stop_atr * atr14
    qtd_risco = valor_risco / (stop_reais * preco) if preco > _zero else _zero

    # --- 2. limites ---
    max_ativo_reais = limites.exposicao_max_ativo * capital - exposicao_atual_ativo
    max_setor_reais = limites.exposicao_max_setor * capital - exposicao_atual_setor
    max_adtv_reais = limites.max_participacao_adtv * vol21d if vol21d else Decimal("inf")
    max_caixa_reais = caixa

    tetos_reais = [max_ativo_reais, max_setor_reais, max_adtv_reais, max_caixa_reais]
    teto_reais = max(min(tetos_reais), _zero)
    qtd_teto = teto_reais / preco if preco > _zero else _zero
    qtd = min(qtd_risco, qtd_teto)

    # --- 3. redutores ---
    redutores: list[str] = []
    if faixa == MEDIA:
        qtd = qtd * limites.redutor_liquidez_media
        redutores.append("LIQUIDEZ_MEDIA")
    if percentil_volatilidade is not None and percentil_volatilidade > Decimal("0.80"):
        qtd = qtd * limites.redutor_vol_p80
        redutores.append("VOL_P80")

    # --- 4. arredondamento ---
    qtd_total = int(qtd)           # trunca para inteiro (nao arredonda para cima)
    qtd_inteira = (qtd_total // 100) * 100
    qtd_fracionaria = qtd_total - qtd_inteira

    valor_final = Decimal(qtd_total) * preco

    if caixa < limites.posicao_minima:
        return ResultadoSizing(False, CAIXA_INSUFICIENTE, "caixa insuficiente para abrir uma posicao",
                               0, 0, _zero, redutores)

    if valor_final < limites.posicao_minima:
        return ResultadoSizing(False, POSICAO_ABAIXO_DO_MINIMO,
                               f"valor final R$ {valor_final} abaixo do minimo de R$ {limites.posicao_minima}",
                               0, 0, _zero, redutores)

    return ResultadoSizing(True, None, None, qtd_inteira, qtd_fracionaria, valor_final, redutores)
