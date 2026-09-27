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

Limites conhecidos, gravados em observacoes: proventos so cobrem eventos a
partir de 27/09/2026 (ver app/validacao/proventos.py - fonte da B3 so devolve
os ultimos ~12 meses por consulta, sinais mais antigos ficam sem ajuste),
universo de hoje olhando para tras (vies de sobrevivencia) e TTM so existe
para os ultimos anos carregados.
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

from sqlalchemy import text

from app.core.analysis.limiares import LIMIARES_ATUAIS, Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.regra_v2 import VERSAO_REGRA_V2, EntradaV2, posicao_no_range, recomendar_v2
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import TAXA_REFERENCIA_GRAHAM, ValuationAnalyzer
from app.core.analysis.versao_regra import VERSAO_REGRA
from app.validacao.proventos import agrupar_por_emissor_e_data, codigo_emissor
from app.validacao.avaliador import (
    CUSTO_IDA_E_VOLTA_PADRAO,
    HORIZONTES_PREGOES,
    LIMIAR_SALTO_SUSPEITO,
    Pregao,
    ResultadoHorizonte,
    avaliar,
    direcao,
)
from app.validacao.ponto_no_tempo import DadosPontoNoTempo

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
    resultados: dict[int, ResultadoHorizonte] = field(default_factory=dict)


@dataclass(frozen=True)
class Avaliacao:
    simbolo: str
    versao: str
    periodo: str
    recomendacao: str
    resultado: ResultadoHorizonte


def montar_series(linhas, identidades: dict[str, tuple[str, bool]], universo: set[str]) -> dict[str, list[Vela]]:
    """Serie por codigo CANONICO, emendando codigos antigos do mesmo papel
    (ELET3 ate a troca, AXIA3 depois). Em data repetida, o canonico vence."""
    por_ativo: dict[str, dict[date, tuple[bool, Vela]]] = defaultdict(dict)
    for simbolo, dia, abertura, maxima, minima, fechamento in linhas:
        canonico, continuo = identidades.get(simbolo, (simbolo, True))
        if canonico not in universo or not continuo or not abertura or not fechamento:
            continue
        e_canonico = simbolo == canonico
        atual = por_ativo[canonico].get(dia)
        if atual and atual[0] and not e_canonico:
            continue
        vela = Vela(dia, Decimal(str(abertura)), Decimal(str(maxima)), Decimal(str(minima)), Decimal(str(fechamento)))
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
    valuation = ValuationAnalyzer(limiares=limiares).analyze(snapshot, taxa_juros, "BACKTEST", lpas_anuais, vpa)
    if not valuation["valido"]:
        return "SEM_DADOS"
    contexto = TechnicalContextAnalyzer().analyze(snapshot)
    return RecommendationPolicy(limiares).define_recommendation(valuation, contexto["_raw"]["posicao_52w"])


def regra_v1_antiga(a: Amostra) -> str:
    """2026.09.26-1: sem juros (Y = 4,4), LPA do ultimo anual, venda com margem < 0."""
    return recomendar_v1(a, Limiares(margem_venda=0.0), TAXA_REFERENCIA_GRAHAM, a.lpa_anual)


def regra_v1_atual(a: Amostra, limiares: Limiares = LIMIARES_ATUAIS) -> str:
    """VERSAO_REGRA: Selic como Y (CDI anualizado quando nao ha historico da
    Selic no dia), LPA normalizado pelos anuais entregues, Graham Number."""
    taxa = a.selic if a.selic is not None else a.juros_cdi
    return recomendar_v1(a, limiares, taxa, a.lpa_recente, a.lpas_anuais, a.vpa)


def regra_v2(a: Amostra) -> str:
    return recomendar_v2(
        EntradaV2(a.preco, a.lpa_recente, a.juros_cdi, a.ipca_12m,
                  posicao_no_range(a.preco, a.minima_52s, a.maxima_52s), a.fonte_lpa_recente)
    ).recomendacao


REGRAS: dict[str, Callable[[Amostra], str]] = {
    VERSAO_V1_ANTIGA: regra_v1_antiga,
    VERSAO_REGRA: regra_v1_atual,
    VERSAO_REGRA_V2: regra_v2,
}


# --- amostras ----------------------------------------------------------------


def montar_amostras(db, inicio: date, corte: date, horizontes=HORIZONTES_PREGOES) -> tuple[list[Amostra], list[str], int]:
    """(amostras, observacoes, quantos ativos com serie). Parte cara do
    backtest, feita uma vez so."""
    universo = {s for (s,) in db.execute(text("SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE"))}
    identidades = {
        s: (c, bool(k))
        for s, c, k in db.execute(text("SELECT simbolo, simbolo_canonico, continuidade_preco FROM ativo_identidade"))
    }
    linhas = db.execute(
        text("SELECT simbolo, data_pregao, abertura, maxima, minima, fechamento FROM cotacao_b3_diaria ORDER BY data_pregao")
    ).all()
    series = montar_series(linhas, identidades, universo)
    dados = DadosPontoNoTempo.carregar(db)
    cdi = {
        d: Decimal(str(v))
        for d, v in db.execute(text("SELECT data, valor FROM indice_macro WHERE codigo_serie='CDI' AND valor IS NOT NULL"))
    }
    datas_cdi = sorted(cdi)
    # provento_distribuido e do gestor-ativos-brutos (ClienteB3Proventos); so
    # tem cobertura a partir de 27/09/2026 (limite da fonte, ver proventos.py).
    proventos_por_emissor = agrupar_por_emissor_e_data(
        db.execute(text("SELECT simbolo, tipo, ultima_data_com_direito, valor_por_acao FROM provento_distribuido")).all()
    )

    observacoes = []
    sem_serie = sorted(universo - set(series))
    if sem_serie:
        observacoes.append(f"Sem COTAHIST (fora do backtest): {', '.join(sem_serie)}")
    if len(series) < 5:
        raise RuntimeError(f"So {len(series)} ativos com COTAHIST; carregue o --cotahist antes do backtest")
    if dados.selic_em(inicio) is None:
        observacoes.append("Sem histórico da Selic no início do período: a v1 usa o CDI anualizado como Y até ele existir.")

    pregoes = {s: [Pregao(v.data, v.abertura, v.fechamento) for v in velas] for s, velas in series.items()}
    indice_por_data = {s: {p.data: i for i, p in enumerate(ps)} for s, ps in pregoes.items()}
    cache_carteira: dict[tuple[date, date], dict[str, list[Pregao]]] = {}

    def carteira_entre(entrada: date, saida: date) -> dict[str, list[Pregao]]:
        chave = (entrada, saida)
        if chave not in cache_carteira:
            recorte = {}
            for s, ps in pregoes.items():
                i, j = indice_por_data[s].get(entrada), indice_por_data[s].get(saida)
                if i is not None and j is not None:
                    recorte[s] = ps[i : j + 1]
            cache_carteira[chave] = recorte
        return cache_carteira[chave]

    def cdi_entre(entrada: date, saida: date) -> dict[date, Decimal]:
        i, j = bisect.bisect_left(datas_cdi, entrada), bisect.bisect_left(datas_cdi, saida)
        return {d: cdi[d] for d in datas_cdi[i:j]}

    amostras: list[Amostra] = []
    for simbolo, velas in sorted(series.items()):
        serie = pregoes[simbolo]
        for i in primeiros_pregoes_do_mes(velas):
            dia = velas[i].data
            if dia < inicio or i < PREGOES_52_SEMANAS:
                continue
            janela = velas[i - PREGOES_52_SEMANAS + 1 : i + 1]
            lpa_anual, _ = dados.lpa_em(simbolo, dia, usar_ttm=False)
            lpa_recente, fonte = dados.lpa_em(simbolo, dia, usar_ttm=True)
            lpas_anuais, vpa = dados.anuais_em(simbolo, dia)
            amostra = Amostra(
                simbolo=simbolo, dia=dia, periodo="CALIBRACAO" if dia <= corte else "TESTE",
                preco=float(velas[i].fechamento),
                minima_52s=float(min(v.minima for v in janela)), maxima_52s=float(max(v.maxima for v in janela)),
                lpa_anual=lpa_anual, lpa_recente=lpa_recente, fonte_lpa_recente=fonte,
                lpas_anuais=lpas_anuais, vpa=vpa, selic=dados.selic_em(dia), juros_cdi=dados.juros_em(dia),
                ipca_12m=dados.ipca_12m_em(dia),
            )
            for horizonte in horizontes:
                if i + horizonte >= len(serie):
                    continue
                entrada, saida = serie[i + 1].data, serie[i + horizonte].data
                resultado = avaliar(
                    dia, None, serie[i : i + horizonte + 1], horizonte,
                    carteira=carteira_entre(entrada, saida), cdi_diario=cdi_entre(entrada, saida),
                    proventos=proventos_por_emissor.get(codigo_emissor(simbolo), {}),
                    proventos_carteira=proventos_por_emissor,
                )
                if resultado is not None:
                    amostra.resultados[horizonte] = resultado
            amostras.append(amostra)
    return amostras, observacoes, len(series)


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
                avaliacoes.append(Avaliacao(a.simbolo, versao, a.periodo, recomendacao, resultado))
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
            "Retorno inclui proventos (data-com) só a partir de 27/09/2026 - fonte da B3 só "
            "cobre os últimos ~12 meses por consulta; sinais anteriores não têm ajuste."
        )
        observacoes.append("Universo de hoje aplicado ao passado (viés de sobrevivência).")

        placar = agregar(avaliacoes)
        self._validar(placar, avaliacoes)
        for linha in placar:
            db.execute(
                text(
                    "INSERT INTO backtest_placar (execucao_id, versao_regra, periodo, recomendacao, horizonte, "
                    "avaliados, acertos, taxa_base, retorno_medio, excesso_medio_cdi, excesso_medio_carteira, "
                    "n_excesso_cdi, desvio_excesso_cdi, n_excesso_carteira, desvio_excesso_carteira) "
                    "VALUES (:e, :versao, :periodo, :recomendacao, :horizonte, :avaliados, :acertos, :taxa_base, "
                    ":retorno_medio, :excesso_cdi, :excesso_carteira, :n_excesso_cdi, :desvio_excesso_cdi, "
                    ":n_excesso_carteira, :desvio_excesso_carteira)"
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
            "versoes": [VERSAO_REGRA, VERSAO_REGRA_V2, VERSAO_V1_ANTIGA],
            "limiares_v1": LIMIARES_ATUAIS.como_dict(),
            "frequencia": "primeiro pregao de cada mes",
            "horizontes_pregoes": list(self._horizontes),
            "custo_ida_e_volta": str(CUSTO_IDA_E_VOLTA_PADRAO),
            "fonte_preco": "B3 COTAHIST (bruto) + proventos de provento_distribuido (so a partir de 27/09/2026)",
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

    grupos: dict[tuple, list[ResultadoHorizonte]] = defaultdict(list)
    for a in validas:
        grupos[a.versao, a.periodo, a.recomendacao, a.resultado.horizonte].append(a.resultado)

    linhas = []
    for (versao, periodo, recomendacao, horizonte), resultados in sorted(grupos.items()):
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
        })
    return linhas


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
