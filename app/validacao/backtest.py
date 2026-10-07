"""Backtest walk-forward das regras (contrato infra#CTR-14).

    python -m app.validacao.backtest [--corte 2022-12-31] [--inicio 2017-01-01]

Como funciona:
  - Uma AMOSTRA por ativo no primeiro pregao de cada mes, com o que se sabia
    naquele dia: preco oficial da B3 (COTAHIST), faixa de 52 semanas dos
    ultimos 252 pregoes, balancos ja ENTREGUES a CVM (DT_RECEB), Selic, CDI
    e IPCA ja publicados. Cada amostra e medida uma vez por horizonte pelo
    MESMO motor do diario (avaliador.py).
  - Cada REGRA e so uma funcao amostra -> recomendacao, aplicada depois:
      v1 antiga  2026.09.26-1  Graham sem juros, LPA do ultimo anual, venda com margem < 0;
      v1 atual   VERSAO_REGRA  juros (Selic), LPA normalizado, Graham Number,
                               faixa neutra, limiares de limiares.py;
      v2 sombra  regra_v2.py.
    Separar as duas coisas e o que deixa a calibracao (calibracao.py) testar
    centenas de limiares sem refazer a parte cara.
  - Sinais ate o corte formam a CALIBRACAO (onde e licito ajustar limiar);
    depois dele, o TESTE, que nao pode ser usado para ajustar nada.

Limites conhecidos, gravados em observacoes: proventos cobrem uma janela
movel de ~12 meses anteriores a CADA coleta da B3 (ver app/validacao/
proventos.py - confirmado: a primeira coleta em 27/09/2026 trouxe eventos
desde 26/09/2025), nao um corte fixo dali pra frente; sinais fora dessa
janela ficam sem ajuste por ausencia de dado. O universo e o do ano de cada
sinal, com quem saiu da bolsa (universo.py); o que resta de sobrevivencia:
papel deslistado no meio da janela nao tem saida e a janela e descartada.
TTM so existe para os ultimos anos carregados.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from logging import Logger

from sqlalchemy import bindparam, text

from app.core.analysis.limiares import LIMIARES_ATUAIS, Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.regra_v2 import VERSAO_REGRA_V2, EntradaV2, posicao_no_range, recomendar_v2
from app.core.analysis.technical_series import TechnicalSeriesAnalyzer
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import TAXA_REFERENCIA_GRAHAM, ValuationAnalyzer
from app.core.analysis.versao_regra import VERSAO_REGRA
from app.core.strategies.mean_reversion_strategy import MeanReversionStrategy
from app.core.strategies.momentum_strategy import MomentumStrategy
from app.fatores.ajuste_preco import ajustar, fator_acumulado
from app.fatores.fonte_proventos import FonteProventos
from app.fatores.preco import PREGOES_TRIMESTRE, PregaoFator, spread_mediano
from app.fatores.repositorio import RepositorioFatores
from app.fatores.servico import emendar
from app.validacao.avaliador import (
    CUSTO_IDA_E_VOLTA_PADRAO,
    HORIZONTES_PREGOES,
    LIMIAR_SALTO_SUSPEITO,
    Pregao,
    ResultadoHorizonte,
    avaliar,
    direcao,
    media_da_carteira,
    tem_salto_suspeito,
)
from app.validacao.bootstrap import intervalo_em_blocos
from app.validacao.ponto_no_tempo import DadosPontoNoTempo
from app.validacao.universo import LIQUIDEZ_MINIMA, PREGOES_MINIMOS, universo_por_ano

CORTE_PADRAO = date(2022, 12, 31)
INICIO_PADRAO = date(2017, 1, 1)
PREGOES_52_SEMANAS = 252
VERSAO_V1_ANTIGA = "2026.09.26-1"


@dataclass(frozen=True)
class Vela:
    data: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: Decimal | None = None


@dataclass
class Amostra:
    """O que se sabia no dia do sinal, e o que aconteceu depois."""

    simbolo: str
    dia: date
    periodo: str
    preco: float
    minima_52s: float
    maxima_52s: float
    lpa_anual: float | None  # ultimo anual entregue (como a v1 antiga via)
    lpa_recente: float | None  # TTM se entregue, senao anual (o "LPA atual" da BRAPI)
    fonte_lpa_recente: str
    lpas_anuais: list[float]  # ate 5 exercicios, mais recente primeiro
    vpa: float | None
    selic: float | None
    juros_cdi: float | None
    ipca_12m: float | None
    sinal_momentum: str | None = None
    sinal_reversao: str | None = None
    resultados: dict[int, ResultadoHorizonte] = field(default_factory=dict)


@dataclass(frozen=True)
class Avaliacao:
    simbolo: str
    versao: str
    periodo: str
    recomendacao: str
    resultado: ResultadoHorizonte
    # Houve provento com data-com dentro da janela (TASK-56). A B3 so devolve
    # os ~12 meses anteriores a cada coleta (gerar-insights#TASK-46): nas
    # janelas mais antigas sai False por falta de dado, nao de provento.
    teve_provento: bool = False


def montar_series(linhas, identidades: dict[str, tuple[str, bool]], universo: set[str]) -> dict[str, list[Vela]]:
    """Serie por codigo CANONICO, emendando codigos antigos do mesmo papel
    (ELET3 ate a troca, AXIA3 depois). Em data repetida, o canonico vence."""
    por_ativo: dict[str, dict[date, tuple[bool, Vela]]] = defaultdict(dict)
    for simbolo, dia, abertura, maxima, minima, fechamento, volume in linhas:
        canonico, continuo = identidades.get(simbolo, (simbolo, True))
        if canonico not in universo or not continuo or not abertura or not fechamento:
            continue
        e_canonico = simbolo == canonico
        atual = por_ativo[canonico].get(dia)
        if atual and atual[0] and not e_canonico:
            continue
        vela = Vela(
            dia,
            Decimal(str(abertura)),
            Decimal(str(maxima)),
            Decimal(str(minima)),
            Decimal(str(fechamento)),
            Decimal(str(volume)) if volume is not None else None,
        )
        por_ativo[canonico][dia] = (e_canonico, vela)
    return {s: [v for _, v in sorted(d.values(), key=lambda x: x[1].data)] for s, d in por_ativo.items()}


def primeiros_pregoes_do_mes(velas: list[Vela]) -> list[int]:
    indices, mes_anterior = [], None
    for i, vela in enumerate(velas):
        mes = (vela.data.year, vela.data.month)
        if mes != mes_anterior:
            indices.append(i)
            mes_anterior = mes
    return indices


# --- regras ----------------------------------------------------------------


def recomendar_v1(
    amostra: Amostra,
    limiares: Limiares = LIMIARES_ATUAIS,
    taxa_juros: float | None = None,
    lpa: float | None = None,
    lpas_anuais: list[float] | None = None,
    vpa: float | None = None,
    ipca_12m: float | None = None,
) -> str:
    """Exatamente o caminho dos insights (ValuationAnalyzer + RecommendationPolicy),
    alimentado com o snapshot do dia."""
    if taxa_juros is None or not lpa or lpa <= 0:
        return "SEM_DADOS"
    snapshot = MarketSnapshot(
        symbol=amostra.simbolo, price=amostra.preco, earnings_per_share=lpa, price_earnings=amostra.preco / lpa,
        open_price=None, previous_close=None, day_high=None, day_low=None, volume=None, market_cap=None,
        fifty_two_week_low=amostra.minima_52s, fifty_two_week_high=amostra.maxima_52s,
    )
    valuation = ValuationAnalyzer(limiares=limiares).analyze(
        snapshot, taxa_juros, "BACKTEST", lpas_anuais, vpa, ipca_12m
    )
    if not valuation["valido"]:
        return "SEM_DADOS"
    contexto = TechnicalContextAnalyzer().analyze(snapshot)
    return RecommendationPolicy(limiares).define_recommendation(valuation, contexto["_raw"]["posicao_52w"])


def regra_v1_antiga(a: Amostra) -> str:
    """2026.09.26-1: sem juros (Y = 4,4), LPA do ultimo anual, venda com margem < 0."""
    # Tudo fixado explicitamente: se dependesse dos padroes de Limiares, a
    # regra "antiga" mudaria a cada calibracao (e sumiu quando o padrao virou
    # G_NOMINAL, que exige IPCA).
    return recomendar_v1(
        a, Limiares(margem_venda=0.0, modo_juros="G_REAL", multiplo_base=8.5, margem_compra_forte=20.0,
                    ey_compra_forte=12.0, margem_compra_moderada=20.0, ey_compra_moderada=8.0,
                    posicao_alerta=90.0, margem_alerta=10.0, anos_lpa_min=99),
        TAXA_REFERENCIA_GRAHAM, a.lpa_anual,
    )


def regra_v1_atual(a: Amostra, limiares: Limiares = LIMIARES_ATUAIS) -> str:
    """VERSAO_REGRA: Selic como Y (CDI anualizado quando nao ha historico da
    Selic no dia), LPA normalizado pelos anuais entregues, Graham Number."""
    taxa = a.selic if a.selic is not None else a.juros_cdi
    return recomendar_v1(a, limiares, taxa, a.lpa_recente, a.lpas_anuais, a.vpa, a.ipca_12m)


def regra_v2(a: Amostra) -> str:
    return recomendar_v2(
        EntradaV2(a.preco, a.lpa_recente, a.juros_cdi, a.ipca_12m,
                  posicao_no_range(a.preco, a.minima_52s, a.maxima_52s), a.fonte_lpa_recente)
    ).recomendacao


VERSAO_MOMENTUM = "TECNICO_MOMENTUM_2026.10.07-1"
VERSAO_REVERSAO = "TECNICO_REVERSAO_2026.10.07-1"


def regra_momentum(a: Amostra) -> str:
    return a.sinal_momentum or "SEM_DADOS"


def regra_reversao(a: Amostra) -> str:
    return a.sinal_reversao or "SEM_DADOS"


REGRAS: dict[str, Callable[[Amostra], str]] = {
    VERSAO_V1_ANTIGA: regra_v1_antiga,
    VERSAO_REGRA: regra_v1_atual,
    VERSAO_REGRA_V2: regra_v2,
    VERSAO_MOMENTUM: regra_momentum,
    VERSAO_REVERSAO: regra_reversao,
}


# --- amostras ----------------------------------------------------------------


def sinais_tecnicos_da_janela(velas: list[Vela], janela_minima: int = 20) -> dict[str, str | None]:
    """Classifica momentum e reversão no fechamento do dia da amostra.

    Usa somente candles até o dia do sinal (inclusive): é o mesmo dado
    disponível depois do fechamento, antes da entrada na abertura seguinte.
    Os sinais entram como regras próprias no placar (TASK-52), nunca como
    voto dentro da recomendação de valuation.
    """
    if len(velas) < janela_minima:
        return {"sinal_momentum": None, "sinal_reversao": None}
    recentes = velas[-janela_minima:]
    closes = [float(v.fechamento) for v in recentes if v.fechamento is not None]
    volumes = [float(v.volume) for v in recentes if v.volume is not None]
    metricas = TechnicalSeriesAnalyzer().analyze(closes, volumes)
    if metricas is None:
        return {"sinal_momentum": None, "sinal_reversao": None}

    atual = float(recentes[-1].fechamento)
    volume_score = metricas["score_volume"] if metricas["score_volume"] is not None else 0.0
    minima_52s = float(min(v.minima for v in velas))
    maxima_52s = float(max(v.maxima for v in velas))

    momentum = MomentumStrategy()
    reversao = MeanReversionStrategy()
    return {
        "sinal_momentum": _classificar_sinal(
            momentum.should_buy(atual, metricas["media_movel"], volume_score),
            momentum.should_sell(atual, metricas["media_movel"], volume_score),
        ),
        "sinal_reversao": _classificar_sinal(
            reversao.should_buy(atual, metricas["z_score_fechamento"], minima_52s),
            reversao.should_sell(atual, metricas["z_score_fechamento"], maxima_52s),
        ),
    }


def _classificar_sinal(comprar: bool, vender: bool) -> str:
    if comprar:
        return "COMPRA_TECNICA"
    if vender:
        return "VENDA_TECNICA"
    return "NEUTRO_TECNICO"


def montar_amostras(db, inicio: date, corte: date, horizontes=HORIZONTES_PREGOES) -> tuple[list[Amostra], list[str], int]:
    """(amostras, observacoes, quantos ativos com serie). Parte cara do
    backtest, feita uma vez so.

    Universo amplo e point-in-time (TASK-51, universo.py): a acao so gera
    amostra nos anos em que estava no universo, e a regua da carteira e a
    media dos membros do universo do ano da entrada."""
    identidades = {
        s: (c, bool(k))
        for s, c, k in db.execute(text("SELECT simbolo, simbolo_canonico, continuidade_preco FROM ativo_identidade"))
    }
    universo_ano = universo_por_ano(db, identidades)
    if not universo_ano:
        raise RuntimeError("Universo vazio: carregue o COTAHIST amplo (etl --cotahist) antes do backtest")
    universo = set().union(*universo_ano.values())
    # So os codigos do universo (e os antigos do mesmo papel): a tabela tem
    # ~1,2 milhao de linhas de ~1.800 codigos.
    codigos = universo | {s for s, (c, continuo) in identidades.items() if c in universo and continuo}
    linhas = db.execute(
        text(
            "SELECT simbolo, data_pregao, abertura, maxima, minima, fechamento, volume FROM cotacao_b3_diaria "
            "WHERE simbolo IN :codigos ORDER BY data_pregao"
        ).bindparams(bindparam("codigos", expanding=True)),
        {"codigos": sorted(codigos)},
    ).all()
    brutas = montar_series(linhas, identidades, universo)
    # LAC-INS-2: retornos sobre o preco ajustado por evento corporativo; o
    # valuation do dia continua no preco BRUTO (o LPA e por acao da epoca).
    repositorio_fatores = RepositorioFatores()
    eventos = repositorio_fatores.eventos_corporativos(db)
    series = {s: ajustar(velas, eventos.get(s, [])) for s, velas in brutas.items()}
    spreads = _spreads_por_papel(db, repositorio_fatores, codigos, identidades)
    dados = DadosPontoNoTempo.carregar(db)
    cdi = {
        d: Decimal(str(v))
        for d, v in db.execute(text("SELECT data, valor FROM indice_macro WHERE codigo_serie='CDI' AND valor IS NOT NULL"))
    }
    datas_cdi = sorted(cdi)
    # LAC-INS-1: provento_distribuido (B3, ~12 meses por coleta) mais a DVA
    # (provento_contabil) antes dele, em R$ por acao da epoca; aqui, na escala
    # do preco ajustado (valor x fator dos eventos posteriores a data).
    fonte_proventos = FonteProventos.carregar(db, repositorio_fatores)
    proventos_por_papel = {
        s: {d: v * fator_acumulado(eventos.get(s, []), d) for d, v in fonte_proventos.do_papel(s).items()}
        for s in series
    }

    observacoes = [
        f"Universo por ano (>= {PREGOES_MINIMOS} pregões e volume médio >= R$ {LIQUIDEZ_MINIMA / 1e6:.0f} mi/dia "
        "no ano anterior, sem units nem BDRs, incluindo quem saiu da bolsa): "
        + ", ".join(f"{ano}: {len(membros)}" for ano, membros in sorted(universo_ano.items()))
    ]
    if len(series) < 5:
        raise RuntimeError(f"So {len(series)} ativos com COTAHIST; carregue o --cotahist antes do backtest")
    if dados.selic_em(inicio) is None:
        observacoes.append("Sem histórico da Selic no início do período: a v1 usa o CDI anualizado como Y até ele existir.")

    pregoes = {s: [Pregao(v.data, v.abertura, v.fechamento) for v in velas] for s, velas in series.items()}
    indice_por_data = {s: {p.data: i for i, p in enumerate(ps)} for s, ps in pregoes.items()}
    cache_media: dict[tuple[date, date], tuple[Decimal | None, int | None]] = {}
    contagem_eventos: dict[str, int] = defaultdict(int)

    def media_entre(entrada: date, saida: date) -> tuple[Decimal | None, int | None]:
        """Regua da carteira: membros do universo do ano da entrada, uma vez por janela."""
        chave = (entrada, saida)
        if chave not in cache_media:
            recorte = {}
            for s in universo_ano.get(entrada.year, set()):
                ps = pregoes.get(s)
                if ps is None:
                    continue
                i, j = indice_por_data[s].get(entrada), indice_por_data[s].get(saida)
                if i is not None and j is not None:
                    recorte[s] = ps[i : j + 1]
            cache_media[chave] = media_da_carteira(recorte, entrada, saida, proventos_por_papel, por_papel=True)
        return cache_media[chave]

    def cdi_entre(entrada: date, saida: date) -> dict[date, Decimal]:
        i, j = bisect.bisect_left(datas_cdi, entrada), bisect.bisect_left(datas_cdi, saida)
        return {d: cdi[d] for d in datas_cdi[i:j]}

    amostras: list[Amostra] = []
    for simbolo, velas in sorted(series.items()):
        serie = pregoes[simbolo]
        brutos = brutas[simbolo]
        eventos_do_papel = eventos.get(simbolo, [])
        for i in primeiros_pregoes_do_mes(velas):
            dia = velas[i].data
            if dia < inicio or i < PREGOES_52_SEMANAS or simbolo not in universo_ano.get(dia.year, set()):
                continue
            # Faixa de 52 semanas na escala do preco do DIA (a do LPA): a
            # janela ajustada, trazida de volta pelo fator vigente no dia.
            escala = fator_acumulado(eventos_do_papel, dia)
            janela = velas[i - PREGOES_52_SEMANAS + 1 : i + 1]
            lpa_anual, _ = dados.lpa_em(simbolo, dia, usar_ttm=False)
            lpa_recente, fonte = dados.lpa_em(simbolo, dia, usar_ttm=True)
            lpas_anuais, vpa = dados.anuais_em(simbolo, dia)
            amostra = Amostra(
                simbolo=simbolo, dia=dia, periodo="CALIBRACAO" if dia <= corte else "TESTE",
                preco=float(brutos[i].fechamento),
                minima_52s=float(min(v.minima for v in janela) / escala),
                maxima_52s=float(max(v.maxima for v in janela) / escala),
                lpa_anual=lpa_anual, lpa_recente=lpa_recente, fonte_lpa_recente=fonte,
                lpas_anuais=lpas_anuais, vpa=vpa, selic=dados.selic_em(dia), juros_cdi=dados.juros_em(dia),
                ipca_12m=dados.ipca_12m_em(dia),
                **sinais_tecnicos_da_janela(velas[max(0, i - PREGOES_52_SEMANAS + 1) : i + 1]),
            )
            custo = custo_pelo_spread(spreads.get(simbolo, []), dia)
            for horizonte in horizontes:
                if i + horizonte >= len(serie):
                    continue
                entrada, saida = serie[i + 1].data, serie[i + horizonte].data
                resultado = avaliar(
                    dia, None, serie[i : i + horizonte + 1], horizonte,
                    cdi_diario=cdi_entre(entrada, saida),
                    custo_ida_e_volta=custo,
                    custo_carteira=CUSTO_IDA_E_VOLTA_PADRAO,
                    proventos=proventos_por_papel.get(simbolo, {}),
                    media_carteira_pronta=media_entre(entrada, saida),
                )
                if resultado is not None:
                    amostra.resultados[horizonte] = resultado
                    bruto = [Pregao(v.data, v.abertura, v.fechamento) for v in brutos[i : i + horizonte + 1]]
                    if not resultado.evento_suspeito and tem_salto_suspeito(bruto):
                        contagem_eventos["janelas_recuperadas"] += 1
            amostras.append(amostra)
    if eventos:
        observacoes.append(
            f"Preço ajustado por {sum(len(v) for v in eventos.values())} evento(s) corporativo(s) "
            f"(evento_corporativo); {contagem_eventos['janelas_recuperadas']} janela(s) que antes eram "
            "descartadas como provável desdobramento voltaram a contar."
        )
    if any(fonte_proventos.do_papel(s) for s in series):
        observacoes.append("Proventos: provento_distribuido (B3) e, antes dele, a DVA da CVM repartida pelas datas ex.")
    if spreads:
        observacoes.append(
            "Custo por sinal: spread mediano de 63 pregões (melhor oferta de venda - de compra, sobre o preço médio), "
            f"com piso de {CUSTO_IDA_E_VOLTA_PADRAO:.2%} ida e volta; a carteira paga o piso."
        )
    return amostras, observacoes, len(series)


def custo_pelo_spread(pregoes: list[PregaoFator], dia: date) -> Decimal:
    """Metade do spread em cada ponta = um spread na ida e volta, com piso."""
    datas = [p.data for p in pregoes]
    i = bisect.bisect_left(datas, dia)
    spread = spread_mediano(pregoes[max(0, i - PREGOES_TRIMESTRE) : i]) if i else None
    if spread is None:
        return CUSTO_IDA_E_VOLTA_PADRAO
    return max(CUSTO_IDA_E_VOLTA_PADRAO, Decimal(str(round(spread, 6))))


def _spreads_por_papel(db, repositorio: RepositorioFatores, codigos: set[str],
                       identidades: dict[str, tuple[str, bool]]) -> dict[str, list[PregaoFator]]:
    """Series com as melhores ofertas (V16), por codigo canonico. Sem as
    colunas ainda, vazio: o custo fica no piso para todos."""
    if "melhor_oferta_compra" not in repositorio.colunas(db, "cotacao_b3_diaria"):
        return {}
    universo = {identidades.get(c, (c, True))[0] for c in codigos}
    return emendar(repositorio.series(db, codigos), identidades, universo)


def aplicar(amostras: list[Amostra], regras: dict[str, Callable[[Amostra], str]]) -> list[Avaliacao]:
    """Uma avaliacao por (amostra, horizonte, regra) com recomendacao valida;
    o acerto e recalculado na direcao da recomendacao daquela regra."""
    avaliacoes = []
    for a in amostras:
        for versao, regra in regras.items():
            recomendacao = regra(a)
            if recomendacao == "SEM_DADOS":
                continue
            sentido = direcao(recomendacao)
            for base in a.resultados.values():
                resultado = replace(base, acerto=None if sentido == 0 else (base.retorno_liquido * sentido) > 0)
                avaliacoes.append(
                    Avaliacao(a.simbolo, versao, a.periodo, recomendacao, resultado,
                              teve_provento=resultado.proventos_periodo > 0)
                )
    return avaliacoes


class Backtest:
    def __init__(self, fabrica_de_sessao, logger: Logger, corte: date = CORTE_PADRAO,
                 inicio: date = INICIO_PADRAO, horizontes=HORIZONTES_PREGOES):
        self._sessao = fabrica_de_sessao
        self._logger = logger
        self._corte = corte
        self._inicio = inicio
        self._horizontes = tuple(horizontes)

    def executar(self) -> int:
        with self._sessao() as db:
            execucao_id = db.execute(
                text("INSERT INTO backtest_execucao (status, corte_calibracao) VALUES ('EM_ANDAMENTO', :c)"),
                {"c": self._corte},
            ).lastrowid
            db.commit()
            try:
                resumo = self._rodar(db, execucao_id)
            except Exception as erro:
                db.rollback()
                db.execute(
                    text("UPDATE backtest_execucao SET status='ERRO', finalizado_em=NOW(), observacoes=:o WHERE id=:id"),
                    {"o": str(erro)[:2000], "id": execucao_id},
                )
                _registrar_rotina(db, "ERRO", 0, str(erro))
                db.commit()
                raise
            db.commit()
            self._logger.info("Backtest %s concluido | %s", execucao_id, resumo)
            return execucao_id

    def _rodar(self, db, execucao_id: int) -> str:
        amostras, observacoes, ativos = montar_amostras(db, self._inicio, self._corte, self._horizontes)
        avaliacoes = aplicar(amostras, REGRAS)

        com_sinal = {a.simbolo for a in avaliacoes}
        nunca = sorted({a.simbolo for a in amostras} - com_sinal)
        if nunca:
            observacoes.append(f"Sem nenhum balanço entregue no período (fora do placar): {', '.join(nunca)}")
        sem_dado = sum(1 for a in amostras if regra_v1_atual(a) == "SEM_DADOS")
        if sem_dado:
            observacoes.append(
                f"{sem_dado} de {len(amostras)} combinações ativo-mês sem sinal na v1 atual "
                "(sem balanço entregue ou lucro médio não positivo)"
            )
        suspeitas = sum(r.evento_suspeito for a in amostras for r in a.resultados.values())
        janelas = sum(len(a.resultados) for a in amostras)
        if janelas:
            observacoes.append(
                f"{suspeitas} de {janelas} janelas com salto de {LIMIAR_SALTO_SUSPEITO:.0%} ou mais "
                "(provável desdobramento) ficaram fora do placar"
            )
        observacoes.append(
            "Retorno inclui proventos (data-com) numa janela móvel de ~12 meses "
            "anteriores a cada coleta da B3; sinais fora dessa janela não têm ajuste."
        )
        observacoes.append(
            "Janela de papel que saiu da bolsa antes do fim não tem preço de saída e é descartada "
            "(resto de viés de sobrevivência)."
        )

        placar = agregar(avaliacoes)
        self._validar(placar, avaliacoes)
        for linha in placar:
            db.execute(
                text(
                    "INSERT INTO backtest_placar (execucao_id, versao_regra, periodo, recomendacao, horizonte, "
                    "avaliados, acertos, taxa_base, retorno_medio, excesso_medio_cdi, excesso_medio_carteira, "
                    "n_excesso_cdi, desvio_excesso_cdi, n_excesso_carteira, desvio_excesso_carteira, "
                    "janelas_com_provento, ic_acerto_inferior, ic_acerto_superior, "
                    "ic_excesso_carteira_inferior, ic_excesso_carteira_superior, meses_bootstrap) "
                    "VALUES (:e, :versao, :periodo, :recomendacao, :horizonte, :avaliados, :acertos, :taxa_base, "
                    ":retorno_medio, :excesso_cdi, :excesso_carteira, :n_excesso_cdi, :desvio_excesso_cdi, "
                    ":n_excesso_carteira, :desvio_excesso_carteira, :janelas_com_provento, "
                    ":ic_acerto_inferior, :ic_acerto_superior, :ic_excesso_carteira_inferior, "
                    ":ic_excesso_carteira_superior, :meses_bootstrap)"
                ),
                {"e": execucao_id, **linha},
            )
        contagem: dict[str, int] = defaultdict(int)
        sinais = set()
        for av in avaliacoes:
            contagem[f"{av.versao} {av.recomendacao}"] += 1
            sinais.add((av.simbolo, av.resultado.data_entrada))
        dias = [a.dia for a in amostras]
        parametros = {
            # A primeira e a oficial, a segunda a sombra, a terceira a referencia antiga.
            "versoes": [VERSAO_REGRA, VERSAO_REGRA_V2, VERSAO_V1_ANTIGA, VERSAO_MOMENTUM, VERSAO_REVERSAO],
            "limiares_v1": LIMIARES_ATUAIS.como_dict(),
            "frequencia": "primeiro pregao de cada mes",
            "horizontes_pregoes": list(self._horizontes),
            "custo_ida_e_volta": f"spread mediano de 63 pregoes por papel, piso {CUSTO_IDA_E_VOLTA_PADRAO}",
            "fonte_preco": "B3 COTAHIST ajustado por evento_corporativo; valuation no preco bruto do dia",
            "fonte_proventos": "provento_distribuido (B3) e, antes dele, DVA da CVM repartida pelas datas ex",
            "fonte_lucro": "CVM pela DT_RECEB; v1 atual: min(LPA recente, media de 3-5 anuais)",
            "fonte_juros": "v1: Selic meta vigente (DEC-02); v2: CDI anualizado",
            "ativos": sorted({a.simbolo for a in amostras}),
            "janelas_por_recomendacao": dict(sorted(contagem.items())),
        }
        db.execute(
            text(
                "UPDATE backtest_execucao SET status='SUCESSO', finalizado_em=NOW(), inicio_periodo=:i, "
                "fim_periodo=:f, ativos=:a, sinais=:s, parametros_json=:p, observacoes=:o WHERE id=:id"
            ),
            {"i": min(dias) if dias else None, "f": max(dias) if dias else None, "a": ativos,
             "s": len(amostras), "p": json.dumps(parametros, ensure_ascii=False),
             "o": "\n".join(observacoes), "id": execucao_id},
        )
        _registrar_rotina(db, "SUCESSO", len(placar))
        return f"ativos={ativos} amostras={len(amostras)} avaliacoes={len(avaliacoes)} linhas={len(placar)}"

    def _validar(self, placar: list[dict], avaliacoes: list[Avaliacao]) -> None:
        """Checagens de sanidade: falha alto em vez de gravar numero errado."""
        for a in avaliacoes:
            r = a.resultado
            assert r.data_entrada < r.data_saida, f"janela invertida: {r}"
            assert a.periodo in ("CALIBRACAO", "TESTE")
        for linha in placar:
            assert linha["avaliados"] > 0
            if linha["acertos"] is not None:
                assert 0 <= linha["acertos"] <= linha["avaliados"]
            if linha["taxa_base"] is not None:
                assert 0 <= linha["taxa_base"] <= 1


def agregar(avaliacoes: list[Avaliacao]) -> list[dict]:
    """Placar por (versao, periodo, recomendacao, horizonte), sem as janelas
    suspeitas. Taxa-base: fracao de TODAS as janelas do periodo que subiram
    (mesmas janelas para todas as versoes), invertida para venda."""
    validas = [a for a in avaliacoes if not a.resultado.evento_suspeito]
    janelas_unicas: dict[tuple[str, int], dict] = defaultdict(dict)
    for a in validas:
        r = a.resultado
        janelas_unicas[a.periodo, r.horizonte][(a.simbolo, r.data_entrada)] = r.retorno_liquido > 0
    base_alta = {k: sum(v.values()) / len(v) for k, v in janelas_unicas.items() if v}

    grupos: dict[tuple, list[Avaliacao]] = defaultdict(list)
    for a in validas:
        grupos[a.versao, a.periodo, a.recomendacao, a.resultado.horizonte].append(a)

    linhas = []
    for (versao, periodo, recomendacao, horizonte), avaliadas in sorted(grupos.items()):
        resultados = [a.resultado for a in avaliadas]
        sentido = direcao(recomendacao)
        base = base_alta.get((periodo, horizonte))
        taxa_base = None if sentido == 0 or base is None else (base if sentido > 0 else 1 - base)
        linhas.append({
            "versao": versao,
            "periodo": periodo,
            "recomendacao": recomendacao,
            "horizonte": horizonte,
            "avaliados": len(resultados),
            "acertos": None if sentido == 0 else sum(bool(r.acerto) for r in resultados),
            "taxa_base": None if taxa_base is None else round(taxa_base, 6),
            "retorno_medio": _media([r.retorno_liquido for r in resultados]),
            "excesso_cdi": _media([r.excesso_cdi for r in resultados]),
            "excesso_carteira": _media([r.excesso_carteira for r in resultados]),
            # Para o intervalo de confianca (TASK-30): o gestor calcula
            # media +- 1,96 x desvio / raiz(n) com o n de quem TEM o valor.
            "n_excesso_cdi": _contagem([r.excesso_cdi for r in resultados]),
            "desvio_excesso_cdi": _desvio([r.excesso_cdi for r in resultados]),
            "n_excesso_carteira": _contagem([r.excesso_carteira for r in resultados]),
            "desvio_excesso_carteira": _desvio([r.excesso_carteira for r in resultados]),
            # Quantas janelas tiveram o retorno ajustado por provento (TASK-56).
            "janelas_com_provento": sum(1 for a in avaliadas if a.teve_provento),
            **_colunas_bootstrap(resultados, horizonte, sentido),
        })
    return linhas


def _colunas_bootstrap(resultados: list[ResultadoHorizonte], horizonte: int, sentido: int) -> dict:
    """IC por bootstrap em blocos de meses (infra#TASK-31, bootstrap.py)."""
    ic = intervalo_em_blocos(
        [
            (r.data_entrada, None if sentido == 0 else bool(r.acerto),
             None if r.excesso_carteira is None else float(r.excesso_carteira))
            for r in resultados
        ],
        horizonte,
    )
    acerto, excesso = ic["acerto"], ic["excesso"]
    return {
        "ic_acerto_inferior": None if acerto is None else round(acerto[0], 6),
        "ic_acerto_superior": None if acerto is None else round(acerto[1], 6),
        "ic_excesso_carteira_inferior": None if excesso is None else round(excesso[0], 6),
        "ic_excesso_carteira_superior": None if excesso is None else round(excesso[1], 6),
        "meses_bootstrap": ic["meses"],
    }


def _contagem(valores) -> int:
    return sum(1 for v in valores if v is not None)


def _desvio(valores) -> Decimal | None:
    """Desvio-padrao amostral; None com menos de 2 valores (nao ha dispersao)."""
    presentes = [float(v) for v in valores if v is not None]
    if len(presentes) < 2:
        return None
    media = sum(presentes) / len(presentes)
    variancia = sum((v - media) ** 2 for v in presentes) / (len(presentes) - 1)
    return Decimal(str(variancia ** 0.5)).quantize(Decimal("0.000001"))


def _media(valores) -> Decimal | None:
    presentes = [v for v in valores if v is not None]
    return (sum(presentes) / len(presentes)).quantize(Decimal("0.000001")) if presentes else None


def _registrar_rotina(db, status: str, linhas: int, erro: str | None = None) -> None:
    """Deixa rastro em etl_execucao: a saude dos dados mostra quando o
    backtest rodou pela ultima vez, como faz com as cargas."""
    db.execute(
        text(
            "INSERT INTO etl_execucao (fonte, competencia, arquivo, status, linhas_carregadas, mensagem_erro, "
            "finalizado_em) VALUES ('BACKTEST', :c, 'backtest_placar', :s, :l, :e, NOW())"
        ),
        {"c": date.today().isoformat(), "s": status, "l": linhas, "e": erro},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest walk-forward das regras")
    parser.add_argument("--corte", type=date.fromisoformat, default=CORTE_PADRAO,
                        help="ultimo dia da calibracao; depois dele e teste (padrao 2022-12-31)")
    parser.add_argument("--inicio", type=date.fromisoformat, default=INICIO_PADRAO)
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase

    logger = setup_logger()
    inicio = datetime.now()
    execucao = Backtest(ConfigDatabase().session, logger, argumentos.corte, argumentos.inicio).executar()
    logger.info("Backtest %s gravado em %.1fs", execucao, (datetime.now() - inicio).total_seconds())
    return 0


if __name__ == "__main__":
    sys.exit(main())
