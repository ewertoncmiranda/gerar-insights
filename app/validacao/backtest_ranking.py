"""Backtest pelo metodo de ranking em janelas sucessivas (LAC-INS-8 e 9).

Sem comando proprio (DEC-AGT-1): roda no fim da etapa semanal de backtest da rotina da manha
(`app.validacao.backtest`, as sextas), para todas as versoes, com as amostras montadas uma vez.

Cada versao tem a sua hipotese PRE-REGISTRADA em `HIPOTESES` (escrita antes de qualquer resultado) e
gravada na execucao antes de rodar. `numero_tentativa` conta hipoteses DISTINTAS da mesma familia:
reexecutar a mesma hipotese com mais dados nao e tentativa nova (nao infla o N da correcao); mudar o
texto da hipotese (ou o score) e. O resultado de cada mes vai para backtest_ranking_mes/quintil e a
decisao de promocao (LAC-INS-9), para observacoes e parametros_json da execucao.

Versoes (score: maior = mais atraente):
  VALOR               media dos percentis de EARNINGS_YIELD e BOOK_TO_MARKET
  VALOR_QUALIDADE     VALOR + PIOTROSKI e ROIC
  VALOR_MOMENTO       VALOR + MOMENTO_12_1
  GRAHAM_V1           margem de seguranca do cenario base da regra oficial
  VALUATION_SETOR     regra de valuation do grupo de setor (setor_grupo.regra_valuation):
                      GRAHAM -> percentil da margem; PL_SETOR -> EARNINGS_YIELD no setor;
                      PVP_SETOR -> BOOK_TO_MARKET no setor; DIVIDENDOS -> DIVIDEND_YIELD no setor
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from logging import Logger

from sqlalchemy import text

from app.core.analysis.limiares import LIMIARES_ATUAIS
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.valuation import ValuationAnalyzer
from app.fatores.mercado import regressao
from app.fatores.percentis import percentis
from app.fatores.repositorio import RepositorioFatores
from app.fatores.servico import VERSAO_MERCADO
from app.validacao.avaliador import HORIZONTES_PREGOES
from app.validacao.backtest import Amostra, montar_amostras
from app.validacao.ranking import (
    Janela,
    MesRanking,
    decidir_promocao,
    janelas_sucessivas,
    medir_mes,
)

INICIO_PADRAO = date(2011, 1, 1)
HORIZONTE_DECISAO = 63
HORIZONTE_ALFA = 21
FATORES_REFERENCIA = ("MKT", "SMB", "HML", "WML", "IML", "QMJ")

COMPONENTES = {
    "VALOR": ("EARNINGS_YIELD", "BOOK_TO_MARKET"),
    "VALOR_QUALIDADE": ("EARNINGS_YIELD", "BOOK_TO_MARKET", "PIOTROSKI", "ROIC"),
    "VALOR_MOMENTO": ("EARNINGS_YIELD", "BOOK_TO_MARKET", "MOMENTO_12_1"),
}
FATOR_POR_REGRA_SETOR = {"PL_SETOR": "EARNINGS_YIELD", "PVP_SETOR": "BOOK_TO_MARKET", "DIVIDENDOS": "DIVIDEND_YIELD"}
VERSOES = (*COMPONENTES, "GRAHAM_V1", "VALUATION_SETOR")

# Pre-registro (LAC-INS-8): o que se espera e por que, escrito em 2026-10-11 ANTES de rodar o ranking
# com os dados do backfill. Mudar um texto conta como tentativa nova da familia.
HIPOTESES = {
    "VALOR": "Acoes com maior earnings yield e book-to-market (mais baratas por lucro e por patrimonio) rendem "
             "mais nos 63 pregoes seguintes que as mais caras, pelo premio de valor documentado na bolsa brasileira.",
    "VALOR_QUALIDADE": "Entre as acoes baratas, as de melhor qualidade (Piotroski e ROIC altos) rendem mais em 63 "
                       "pregoes, porque a qualidade separa o valor real da armadilha de valor.",
    "VALOR_MOMENTO": "Somar o momento de 12-1 meses ao valor melhora o ranking de 63 pregoes, porque valor e "
                     "momento tem correlacao negativa e se complementam.",
    "GRAHAM_V1": "A margem de seguranca de Graham da regra oficial ordena as acoes pelo retorno dos 63 pregoes "
                 "seguintes: maior margem, maior retorno.",
    "VALUATION_SETOR": "Julgar cada acao pela metrica de valuation do seu grupo de setor (P/L, P/VP, dividendos ou "
                       "Graham) ordena melhor o retorno de 63 pregoes que um criterio unico para todos.",
}

Scores = dict[date, dict[str, float]]


def margem_graham(a: Amostra) -> float | None:
    """Margem do cenario base da regra oficial (mesmo caminho dos insights)."""
    taxa = a.selic if a.selic is not None else a.juros_cdi
    if taxa is None or not a.lpa_recente or a.lpa_recente <= 0:
        return None
    snapshot = MarketSnapshot(
        symbol=a.simbolo, price=a.preco, earnings_per_share=a.lpa_recente, price_earnings=a.preco / a.lpa_recente,
        open_price=None, previous_close=None, day_high=None, day_low=None, volume=None, market_cap=None,
        fifty_two_week_low=a.minima_52s, fifty_two_week_high=a.maxima_52s,
    )
    v = ValuationAnalyzer(limiares=LIMIARES_ATUAIS).analyze(snapshot, taxa, "BACKTEST", a.lpas_anuais, a.vpa, a.ipca_12m)
    base = v.get("cenario_base") if v.get("valido") else None
    return None if not base else base.get("margem_seguranca_percent")


def scores_compostos(fatores: dict[tuple[str, date], dict[str, float]], componentes: tuple[str, ...]) -> Scores:
    """Media dos percentis no universo; papel sem algum componente fica de fora do mes."""
    saida: Scores = defaultdict(dict)
    for (simbolo, dia), valores in fatores.items():
        if all(c in valores for c in componentes):
            saida[dia][simbolo] = sum(valores[c] for c in componentes) / len(componentes)
    return dict(saida)


def scores_graham(amostras: list[Amostra]) -> Scores:
    saida: Scores = defaultdict(dict)
    for a in amostras:
        margem = margem_graham(a)
        if margem is not None:
            saida[a.dia][a.simbolo] = float(margem)
    return dict(saida)


def scores_por_setor(graham: Scores, no_setor: dict[tuple[str, date], dict[str, float]],
                     regra_de: dict[str, str]) -> Scores:
    """Cada papel julgado pela regra do seu grupo, todos em percentil [0, 1]."""
    saida: Scores = defaultdict(dict)
    for dia, margens in graham.items():
        pct_graham = percentis(margens)
        for simbolo in set(margens) | {s for s, d in no_setor if d == dia}:
            regra = regra_de.get(simbolo, "GRAHAM")
            if regra == "GRAHAM":
                if simbolo in pct_graham:
                    saida[dia][simbolo] = pct_graham[simbolo]
            else:
                valor = no_setor.get((simbolo, dia), {}).get(FATOR_POR_REGRA_SETOR[regra])
                if valor is not None:
                    saida[dia][simbolo] = valor
    return dict(saida)


def medir(amostras: list[Amostra], scores: Scores, horizontes=HORIZONTES_PREGOES) -> list[MesRanking]:
    retornos: dict[tuple[date, int], dict[str, float]] = defaultdict(dict)
    for a in amostras:
        for h, r in a.resultados.items():
            if not r.evento_suspeito:
                retornos[(a.dia, h)][a.simbolo] = float(r.retorno_liquido)
    return [
        medir_mes(dia, h, scores.get(dia, {}), retornos[(dia, h)])
        for (dia, h) in sorted(retornos)
        if scores.get(dia)
    ]


def alfa_contra_fatores(meses: list[MesRanking], fatores_mes: dict[date, dict[str, float]]) -> float | None:
    """Intercepto de (quintil 5 - quintil 1, horizonte ~1 mes) contra MKT..QMJ."""
    y, x = [], []
    for m in meses:
        if m.horizonte != HORIZONTE_ALFA or m.diferenca_extremos is None:
            continue
        fatores = fatores_mes.get(m.data_referencia, {})
        if all(f in fatores for f in FATORES_REFERENCIA):
            y.append(m.diferenca_extremos)
            x.append([fatores[f] for f in FATORES_REFERENCIA])
    resultado = regressao(y, x) if y else None
    return None if resultado is None else resultado[0][0]


def nome_da_janela(janelas: list[Janela], dia: date) -> str:
    return next((j.nome for j in janelas if j.contem_teste(dia)), "TREINO")


def numero_da_tentativa(hipoteses_anteriores: list[str], hipotese: str) -> int:
    """Posicao (1..N) da hipotese entre as DISTINTAS ja registradas na familia, em ordem de registro.

    A mesma hipotese reexecutada mantem o numero; hipotese nova vira a seguinte.
    """
    distintas: list[str] = []
    for h in hipoteses_anteriores:
        h = (h or "").strip()
        if h and h not in distintas:
            distintas.append(h)
    alvo = hipotese.strip()
    return distintas.index(alvo) + 1 if alvo in distintas else len(distintas) + 1


class BacktestRanking:
    def __init__(self, fabrica_de_sessao, logger: Logger, repositorio: RepositorioFatores | None = None):
        self._sessao = fabrica_de_sessao
        self._logger = logger
        self._repo = repositorio or RepositorioFatores()

    def executar_todas(self, inicio: date = INICIO_PADRAO, versoes=VERSOES) -> dict[str, int | None]:
        """Todas as versoes com a hipotese pre-registrada, montando as amostras (parte cara) uma vez.

        A falha de uma versao (ex.: fatores ainda nao calculados) fica registrada nela e nao derruba as
        outras. Devolve {versao: id da execucao, ou None se falhou}.
        """
        with self._sessao() as db:
            amostras, observacoes, ativos = montar_amostras(db, inicio, date.max)
        saida: dict[str, int | None] = {}
        for versao in versoes:
            try:
                saida[versao] = self.executar(versao, HIPOTESES[versao], inicio,
                                              preparadas=(amostras, list(observacoes), ativos))
            except Exception as erro:  # noqa: BLE001 - uma versao nao derruba as outras
                self._logger.error("Backtest por ranking %s falhou: %s", versao, erro)
                saida[versao] = None
        return saida

    def executar(self, versao: str, hipotese: str, inicio: date = INICIO_PADRAO, preparadas=None) -> int:
        if versao not in VERSOES:
            raise ValueError(f"versao desconhecida: {versao} (conhecidas: {', '.join(VERSOES)})")
        if not hipotese or len(hipotese.strip()) < 15:
            raise ValueError("a hipotese e obrigatoria e precisa dizer o que se espera e por que")
        with self._sessao() as db:
            self._repo.exigir(db, "backtest_ranking_mes", "backtest_ranking_quintil", "fator_valor")
            anteriores = [h for (h,) in db.execute(text(
                "SELECT hipotese FROM backtest_execucao WHERE metodo = 'RANKING' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(parametros_json, '$.familia')) = :v ORDER BY id"
            ), {"v": versao})]
            tentativa = numero_da_tentativa(anteriores, hipotese)
            execucao_id = db.execute(text(
                "INSERT INTO backtest_execucao (status, corte_calibracao, metodo, esquema_validacao, hipotese, "
                "numero_tentativa, parametros_json) VALUES ('EM_ANDAMENTO', :c, 'RANKING', 'JANELAS_SUCESSIVAS', "
                ":h, :t, :p)"
            ), {"c": inicio, "h": hipotese.strip(), "t": tentativa,
                "p": json.dumps({"familia": versao}, ensure_ascii=False)}).lastrowid
            db.commit()  # a hipotese fica registrada antes de qualquer numero existir
            try:
                resumo = self._rodar(db, execucao_id, versao, inicio, tentativa, preparadas)
            except Exception as erro:
                db.rollback()
                db.execute(text("UPDATE backtest_execucao SET status='ERRO', finalizado_em=NOW(), observacoes=:o "
                                "WHERE id=:id"), {"o": str(erro)[:2000], "id": execucao_id})
                db.commit()
                raise
            db.commit()
            self._logger.info("Backtest por ranking %s (%s, tentativa %s): %s", execucao_id, versao, tentativa, resumo)
            return execucao_id

    def _scores(self, db, versao: str, amostras: list[Amostra], inicio: date) -> Scores:
        if versao in COMPONENTES:
            return scores_compostos(self._repo.fatores_gravados(db, list(COMPONENTES[versao]), inicio),
                                    COMPONENTES[versao])
        graham = scores_graham(amostras)
        if versao == "GRAHAM_V1":
            return graham
        regra_de = self._regra_de_valuation(db)
        no_setor = self._percentis_de_setor(db, inicio)
        return scores_por_setor(graham, no_setor, regra_de)

    def _regra_de_valuation(self, db) -> dict[str, str]:
        regras = {s: r for s, r in db.execute(text("SELECT setor_cvm, regra_valuation FROM setor_grupo"))}
        setor_por_cnpj = {c: s for c, s in db.execute(text("SELECT cnpj, setor FROM cvm_empresa WHERE setor IS NOT NULL"))}
        return {s: regras[setor_por_cnpj[c]] for s, c in self._repo.cnpj_por_simbolo(db).items()
                if c in setor_por_cnpj and setor_por_cnpj[c] in regras}

    def _percentis_de_setor(self, db, inicio: date) -> dict[tuple[str, date], dict[str, float]]:
        saida: dict[tuple[str, date], dict[str, float]] = defaultdict(dict)
        for simbolo, dia, codigo, pct in db.execute(text(
            "SELECT simbolo, data_referencia, fator_codigo, percentil_setor FROM fator_valor "
            "WHERE data_referencia >= :d AND percentil_setor IS NOT NULL "
            "AND fator_codigo IN ('EARNINGS_YIELD', 'BOOK_TO_MARKET', 'DIVIDEND_YIELD')"
        ), {"d": inicio}):
            saida[(simbolo, dia)][codigo] = float(pct)
        return dict(saida)

    def _rodar(self, db, execucao_id: int, versao: str, inicio: date, tentativa: int, preparadas=None) -> str:
        amostras, observacoes, ativos = preparadas or montar_amostras(db, inicio, date.max)
        scores = self._scores(db, versao, amostras, inicio)
        meses = medir(amostras, scores)
        if not meses:
            raise RuntimeError(f"Nenhum mes com score para {versao}: fatores ainda nao calculados pela etapa mensal")
        anos = sorted({m.data_referencia.year for m in meses})
        janelas = janelas_sucessivas(max(anos[0], INICIO_PADRAO.year), anos[0] + 1, anos[-1])

        for m in meses:
            mes_id = db.execute(text(
                "INSERT INTO backtest_ranking_mes (execucao_id, versao_regra, janela, data_referencia, horizonte, "
                "ic_spearman, n_ativos) VALUES (:e, :v, :j, :d, :h, :ic, :n)"
            ), {"e": execucao_id, "v": versao, "j": nome_da_janela(janelas, m.data_referencia),
                "d": m.data_referencia, "h": m.horizonte, "ic": None if m.ic is None else round(m.ic, 6),
                "n": m.n_ativos}).lastrowid
            for quintil, retorno, n in m.quintis or []:
                db.execute(text(
                    "INSERT INTO backtest_ranking_quintil (ranking_mes_id, quintil, retorno_medio, n_ativos) "
                    "VALUES (:m, :q, :r, :n)"
                ), {"m": mes_id, "q": quintil, "r": round(retorno, 6), "n": n})

        de_teste = [m for m in meses if any(j.contem_teste(m.data_referencia) for j in janelas)]
        alfa = alfa_contra_fatores(de_teste, self._repo.fatores_de_mercado(db, VERSAO_MERCADO))
        decisao = decidir_promocao([m for m in de_teste if m.horizonte == HORIZONTE_DECISAO], HORIZONTE_DECISAO,
                                   tentativa, alfa, None)
        observacoes.append(
            f"Decisao ({versao}, tentativa {tentativa}, horizonte {HORIZONTE_DECISAO}): "
            + ("PROMOVER" if decisao.promover else "NAO PROMOVER - " + "; ".join(decisao.motivos))
        )
        parametros = {
            "familia": versao,
            "horizonte_decisao": HORIZONTE_DECISAO,
            "janelas": [j.nome for j in janelas],
            "ic_medio_teste": decisao.ic_medio,
            "ic_intervalo_teste": decisao.ic_intervalo,
            "quintil5_menos_1_teste": decisao.diferenca_extremos_media,
            "alfa_fatores_referencia": alfa,
            "promover": decisao.promover,
            "motivos": decisao.motivos,
        }
        dias = [m.data_referencia for m in meses]
        db.execute(text(
            "UPDATE backtest_execucao SET status='SUCESSO', finalizado_em=NOW(), inicio_periodo=:i, fim_periodo=:f, "
            "ativos=:a, sinais=:s, parametros_json=:p, observacoes=:o WHERE id=:id"
        ), {"i": min(dias), "f": max(dias), "a": ativos, "s": len(amostras),
            "p": json.dumps(parametros, ensure_ascii=False, default=str), "o": "\n".join(observacoes),
            "id": execucao_id})
        return f"meses={len(meses)} janelas={len(janelas)} promover={decisao.promover}"


# Tipo exportado para quem monta scores em testes.
MontadorDeScores = Callable[[list[Amostra]], Scores]

