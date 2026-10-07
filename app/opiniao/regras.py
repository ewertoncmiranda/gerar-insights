"""Regras puras da opiniao por horizonte: evidencias, opinioes permitidas e risco.

Nada aqui chama banco, rede ou modelo. O modelo de linguagem nunca decide sozinho:
as evidencias e o conjunto de opinioes PERMITIDAS saem destes numeros deterministicos;
o modelo escolhe dentro do conjunto e explica, citando o id de cada evidencia.

Rotulos neutros (DEC-05): SINAL_POSITIVO / SINAL_NEGATIVO / SINAL_NEUTRO / SEM_BASE, nunca
"compra" ou "venda". A tela os colore, sempre com o texto junto da cor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

VERSAO_PROMPT = "1.0"

CURTO, MEDIO, LONGO = 21, 63, 126
HORIZONTES: tuple[int, ...] = (CURTO, MEDIO, LONGO)

POSITIVO = "SINAL_POSITIVO"
NEGATIVO = "SINAL_NEGATIVO"
NEUTRO = "SINAL_NEUTRO"
SEM_BASE = "SEM_BASE"
OPINIOES: tuple[str, ...] = (POSITIVO, NEGATIVO, NEUTRO, SEM_BASE)

RISCO_BAIXO, RISCO_MEDIO, RISCO_ALTO = "RISCO_BAIXO", "RISCO_MEDIO", "RISCO_ALTO"
RISCOS: tuple[str, ...] = (RISCO_BAIXO, RISCO_MEDIO, RISCO_ALTO)

# Fator mais velho que isto nao entra: serie de fatores parada nao descreve o ativo hoje.
IDADE_MAXIMA_FATOR_DIAS = 45
MINIMO_DE_EVIDENCIAS = 2

_FAMILIA_PARA_HORIZONTES: dict[str, tuple[int, ...]] = {
    "PRECO": (CURTO, MEDIO),
    "QUALIDADE": (MEDIO, LONGO),
    "VALOR": (MEDIO, LONGO),
    "EVENTO": (CURTO,),
}

_NIVEL_DO_INSIGHT = {"BAIXO": 0, "MEDIO": 1, "MÉDIO": 1, "ALTO": 2}
_RISCO_DO_NIVEL = (RISCO_BAIXO, RISCO_MEDIO, RISCO_ALTO)


@dataclass(frozen=True)
class Evidencia:
    id: str
    rotulo: str
    valor: str
    direcao: int  # +1 favoravel, -1 desfavoravel, 0 informativa
    horizontes: tuple[int, ...]
    fonte: str  # insight | fator | comunicado


@dataclass
class DossieDeHorizonte:
    pregoes: int
    evidencias: list[Evidencia] = field(default_factory=list)
    permitidas: tuple[str, ...] = (SEM_BASE,)
    risco: str = RISCO_MEDIO
    motivo_sem_base: str | None = None


def _direcao_do_texto(texto: str | None) -> int:
    texto = (texto or "").upper()
    if texto.startswith("COMPRA") or "POSITIV" in texto:
        return 1
    if texto.startswith("VENDA") or "NEGATIV" in texto:
        return -1
    return 0


def evidencias_do_insight(detalhes: dict) -> list[Evidencia]:
    """Evidencias do insight deterministico (payload v2.x de insight_acao.detalhes_json)."""
    saida: list[Evidencia] = []
    resumo = detalhes.get("resumo") or {}
    valuation = detalhes.get("valuation") or {}
    tecnico = detalhes.get("contexto_tecnico_serie") or {}

    recomendacao = resumo.get("recomendacao")
    if recomendacao and recomendacao != "SEM_DADOS":
        direcao = 1 if str(recomendacao).startswith("COMPRA") else (
            -1 if str(recomendacao) in ("VENDA_VALUATION", "ALERTA_RISCO") else 0)
        saida.append(Evidencia("regra_v1", "Regra determinística v1 (valuation)", str(recomendacao),
                               direcao, (MEDIO, LONGO), "insight"))

    base = (valuation.get("cenarios_graham") or {}).get("base") or {}
    margem = base.get("margem_seguranca_percent")
    if isinstance(margem, (int, float)):
        direcao = 1 if margem >= 20 else (-1 if margem <= -20 else 0)
        saida.append(Evidencia("margem_graham_base", "Margem de segurança (Graham, cenário base, %)",
                               f"{margem:.1f}", direcao, (MEDIO, LONGO), "insight"))

    ey = valuation.get("classificacao_earnings_yield")
    if ey:
        direcao = -1 if ey in ("MUITO_BAIXO", "BAIXO") else (1 if ey in ("ALTO", "MUITO_ALTO") else 0)
        saida.append(Evidencia("earnings_yield_classe", "Earnings yield (classe)", str(ey),
                               direcao, (MEDIO, LONGO), "insight"))

    pl = valuation.get("classificacao_pl")
    if pl:
        direcao = -1 if pl == "EXIGENTE" else (1 if pl == "ATRATIVO" else 0)
        saida.append(Evidencia("pl_classe", "P/L (classe)", str(pl), direcao, (MEDIO, LONGO), "insight"))

    for chave, rotulo in (("sinal_momentum", "Sinal técnico de momentum"),
                          ("sinal_reversao", "Sinal técnico de reversão à média")):
        valor = tecnico.get(chave)
        if valor:
            saida.append(Evidencia(chave, rotulo, str(valor), _direcao_do_texto(valor),
                                   (CURTO, MEDIO), "insight"))
    return saida


def evidencias_dos_fatores(fatores: list[dict], hoje: date) -> tuple[list[Evidencia], list[str]]:
    """Fatores do Plano LAC. Devolve (evidencias, dados_atrasados).

    Cada fator traz codigo, familia, direcao_esperada, data_referencia, valor e
    percentil_universo. Fator parado ha mais de IDADE_MAXIMA_FATOR_DIAS e ignorado e declarado.
    """
    saida: list[Evidencia] = []
    atrasados: list[str] = []
    for f in fatores:
        data = f.get("data_referencia")
        if isinstance(data, str):
            data = date.fromisoformat(data[:10])
        if data is None or (hoje - data).days > IDADE_MAXIMA_FATOR_DIAS:
            atrasados.append(f"fator {f.get('codigo')} (último cálculo em {data})")
            continue
        horizontes = _FAMILIA_PARA_HORIZONTES.get(str(f.get("familia", "")).upper())
        percentil = f.get("percentil_universo")
        if not horizontes or percentil is None:
            continue
        direcao_esperada = int(f.get("direcao_esperada") or 0)
        posicao = float(percentil) * 100 if float(percentil) <= 1 else float(percentil)
        if direcao_esperada < 0:
            posicao = 100 - posicao
        direcao = 0 if direcao_esperada == 0 else (1 if posicao >= 66 else (-1 if posicao <= 33 else 0))
        saida.append(Evidencia(f"fator_{str(f['codigo']).lower()}", str(f.get("descricao") or f["codigo"]),
                               f"percentil {float(percentil) * 100 if float(percentil) <= 1 else float(percentil):.0f}",
                               direcao, horizontes, "fator"))
    return saida, atrasados


def evidencia_de_comunicados(fatos_relevantes_30d: int) -> list[Evidencia]:
    if fatos_relevantes_30d <= 0:
        return []
    return [Evidencia("fatos_relevantes_30d", "Fatos relevantes nos últimos 30 dias",
                      str(fatos_relevantes_30d), 0, (CURTO, MEDIO), "comunicado")]


def risco_calculado(detalhes: dict, evidencias: list[Evidencia], pregoes: int) -> str:
    """Risco deterministico: nivel do insight, empurrado para cima por volatilidade alta e fato relevante."""
    nivel = _NIVEL_DO_INSIGHT.get(str((detalhes.get("resumo") or {}).get("nivel_risco", "")).upper(), 1)
    por_id = {e.id: e for e in evidencias}
    if pregoes <= MEDIO:
        volatil = por_id.get("fator_volatilidade_12m")
        if volatil is not None and volatil.direcao < 0:
            nivel += 1
        if "fatos_relevantes_30d" in por_id:
            nivel += 1
    else:
        alavancagem = por_id.get("fator_alavancagem")
        if alavancagem is not None and alavancagem.direcao < 0:
            nivel += 1
    return _RISCO_DO_NIVEL[min(nivel, 2)]


def montar_horizonte(pregoes: int, detalhes: dict, evidencias: list[Evidencia],
                     dados_criticos_atrasados: bool = False) -> DossieDeHorizonte:
    do_horizonte = [e for e in evidencias if pregoes in e.horizontes]
    risco = risco_calculado(detalhes, do_horizonte, pregoes)
    direcionais = [e for e in do_horizonte if e.direcao != 0]
    if dados_criticos_atrasados:
        return DossieDeHorizonte(pregoes, do_horizonte, (SEM_BASE,), risco, "dados críticos atrasados")
    if len(direcionais) < MINIMO_DE_EVIDENCIAS:
        return DossieDeHorizonte(pregoes, do_horizonte, (SEM_BASE,), risco,
                                 f"menos de {MINIMO_DE_EVIDENCIAS} evidências direcionais")
    soma = sum(e.direcao for e in direcionais)
    placar = soma / len(direcionais)
    if soma >= 2 and placar >= 0.5:
        permitidas: tuple[str, ...] = (POSITIVO, NEUTRO)
    elif soma <= -2 and placar <= -0.5:
        permitidas = (NEGATIVO, NEUTRO)
    else:
        permitidas = (NEUTRO, SEM_BASE)
    return DossieDeHorizonte(pregoes, do_horizonte, permitidas, risco)


def montar_dossie(detalhes: dict, fatores: list[dict], fatos_relevantes_30d: int, hoje: date,
                  dados_criticos_atrasados: bool = False) -> tuple[dict[int, DossieDeHorizonte], list[str]]:
    """Dossie por horizonte + a lista do que esta ausente ou atrasado."""
    evidencias = evidencias_do_insight(detalhes)
    do_fator, atrasados = evidencias_dos_fatores(fatores, hoje)
    evidencias += do_fator + evidencia_de_comunicados(fatos_relevantes_30d)
    dossie = {h: montar_horizonte(h, detalhes, evidencias, dados_criticos_atrasados) for h in HORIZONTES}
    if not fatores:
        atrasados.append("fatores do Plano LAC (nenhum cálculo gravado para o ativo)")
    return dossie, atrasados
