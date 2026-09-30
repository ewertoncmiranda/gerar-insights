"""Backtest pelo metodo de ranking em janelas sucessivas (LAC-INS-8 e 9).

    python -m app.validacao.backtest_ranking --versao VALOR \
        --hipotese "acoes baratas por lucro e patrimonio rendem mais em 63 pregoes" [--inicio 2011-01-01]

A hipotese e obrigatoria e fica gravada ANTES de rodar; o numero da
tentativa conta as execucoes anteriores da mesma versao (familia). O
resultado de cada mes vai para backtest_ranking_mes/quintil e a decisao de
promocao (LAC-INS-9), para observacoes e parametros_json da execucao.

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

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
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


class BacktestRanking:
    def __init__(self, fabrica_de_sessao, logger: Logger, repositorio: RepositorioFatores | None = None):
        self._sessao = fabrica_de_sessao
        self._logger = logger
        self._repo = repositorio or RepositorioFatores()

    def executar(self, versao: str, hipotese: str, inicio: date = INICIO_PADRAO) -> int:
        if versao not in VERSOES:
            raise ValueError(f"versao desconhecida: {versao} (conhecidas: {', '.join(VERSOES)})")
        if not hipotese or len(hipotese.strip()) < 15:
            raise ValueError("a hipotese e obrigatoria e precisa dizer o que se espera e por que")
        with self._sessao() as db:
            self._repo.exigir(db, "backtest_ranking_mes", "backtest_ranking_quintil", "fator_valor")
            tentativa = 1 + (db.execute(text(
                "SELECT COUNT(*) FROM backtest_execucao WHERE metodo = 'RANKING' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(parametros_json, '$.familia')) = :v"
            ), {"v": versao}).scalar() or 0)
            execucao_id = db.execute(text(
                "INSERT INTO backtest_execucao (status, corte_calibracao, metodo, esquema_validacao, hipotese, "
                "numero_tentativa, parametros_json) VALUES ('EM_ANDAMENTO', :c, 'RANKING', 'JANELAS_SUCESSIVAS', "
                ":h, :t, :p)"
            ), {"c": inicio, "h": hipotese.strip(), "t": tentativa,
                "p": json.dumps({"familia": versao}, ensure_ascii=False)}).lastrowid
            db.commit()  # a hipotese fica registrada antes de qualquer numero existir
            try:
                resumo = self._rodar(db, execucao_id, versao, inicio, tentativa)
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

    def _rodar(self, db, execucao_id: int, versao: str, inicio: date, tentativa: int) -> str:
        amostras, observacoes, ativos = montar_amostras(db, inicio, date.max)
        scores = self._scores(db, versao, amostras, inicio)
        meses = medir(amostras, scores)
        if not meses:
            raise RuntimeError(f"Nenhum mes com score para {versao}: calcule os fatores (python -m app.fatores calcular)")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest por ranking em janelas sucessivas (Plano LAC)")
    parser.add_argument("--versao", required=True, choices=VERSOES)
    parser.add_argument("--hipotese", required=True, help="o que se espera e por que, escrito ANTES de rodar")
    parser.add_argument("--inicio", type=date.fromisoformat, default=INICIO_PADRAO)
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase

    logger = setup_logger()
    inicio = datetime.now()
    execucao = BacktestRanking(ConfigDatabase().session, logger).executar(argumentos.versao, argumentos.hipotese,
                                                                           argumentos.inicio)
    logger.info("Execucao %s gravada em %.1fs", execucao, (datetime.now() - inicio).total_seconds())
    return 0


# Tipo exportado para quem monta scores em testes.
MontadorDeScores = Callable[[list[Amostra]], Scores]

if __name__ == "__main__":
    sys.exit(main())
