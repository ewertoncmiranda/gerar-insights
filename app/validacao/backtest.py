"""Backtest walk-forward das regras v1 e v2 (contrato infra#CTR-14).

    python -m app.validacao.backtest [--corte 2022-12-31] [--inicio 2017-01-01]

Como funciona:
  - Um sinal por ativo no primeiro pregao de cada mes, com o que se sabia
    naquele dia: preco oficial da B3 (COTAHIST), faixa de 52 semanas dos
    ultimos 252 pregoes, LPA do balanco ja ENTREGUE a CVM (DT_RECEB), CDI e
    IPCA ja publicados.
  - v1 = a regra dos insights (recommendation.py) com LPA do ultimo balanco
    anual entregue; v2 = regra_v2.py (juros, TTM quando existe, faixa neutra).
  - Cada sinal e medido pelo MESMO motor do diario (avaliador.py): entrada na
    abertura seguinte, custo, CDI e media da carteira nas mesmas datas.
  - Sinais ate o corte formam a CALIBRACAO (onde e licito ajustar limiar);
    depois dele, o TESTE, que nao pode ser usado para ajustar nada.

Limites conhecidos, gravados em observacoes: preco sem proventos (pagadora de
dividendo parece pior), universo de hoje olhando para tras (viés de
sobrevivencia) e TTM so existe para os ultimos anos carregados.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from logging import Logger

from sqlalchemy import text

from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.regra_v2 import VERSAO_REGRA_V2, EntradaV2, posicao_no_range, recomendar_v2
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import ValuationAnalyzer
from app.core.analysis.versao_regra import VERSAO_REGRA
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


@dataclass(frozen=True)
class Vela:
    data: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal


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


def sinal_v1(preco: float, lpa: float | None, minima: float, maxima: float) -> str:
    """Exatamente a regra dos insights, alimentada com o snapshot do dia."""
    if not lpa or lpa <= 0:
        return "SEM_DADOS"
    snapshot = MarketSnapshot(
        symbol="", price=preco, earnings_per_share=lpa, price_earnings=preco / lpa, open_price=None,
        previous_close=None, day_high=None, day_low=None, volume=None, market_cap=None,
        fifty_two_week_low=minima, fifty_two_week_high=maxima,
    )
    valuation = ValuationAnalyzer().analyze(snapshot)
    contexto = TechnicalContextAnalyzer().analyze(snapshot)
    return RecommendationPolicy().define_recommendation(valuation, contexto["_raw"]["posicao_52w"])


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
        universo = {s for (s,) in db.execute(text("SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE"))}
        identidades = {
            s: (c, bool(k))
            for s, c, k in db.execute(text("SELECT simbolo, simbolo_canonico, continuidade_preco FROM ativo_identidade"))
        }
        linhas = db.execute(
            text(
                "SELECT simbolo, data_pregao, abertura, maxima, minima, fechamento FROM cotacao_b3_diaria "
                "ORDER BY data_pregao"
            )
        ).all()
        series = montar_series(linhas, identidades, universo)
        dados = DadosPontoNoTempo.carregar(db)
        cdi = {
            d: Decimal(str(v))
            for d, v in db.execute(text("SELECT data, valor FROM indice_macro WHERE codigo_serie='CDI' AND valor IS NOT NULL"))
        }
        datas_cdi = sorted(cdi)

        observacoes = []
        sem_serie = sorted(universo - set(series))
        if sem_serie:
            observacoes.append(f"Sem COTAHIST (fora do backtest): {', '.join(sem_serie)}")
        if len(series) < 5:
            raise RuntimeError(f"So {len(series)} ativos com COTAHIST; carregue o --cotahist antes do backtest")

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

        avaliacoes: list[Avaliacao] = []
        sinais = 0
        com_sinal: set[str] = set()
        meses_sem_balanco = 0
        contagem = defaultdict(int)
        primeira, ultima = None, None

        for simbolo, velas in sorted(series.items()):
            serie = pregoes[simbolo]
            for i in primeiros_pregoes_do_mes(velas):
                dia = velas[i].data
                if dia < self._inicio or i < PREGOES_52_SEMANAS:
                    continue
                janela = velas[i - PREGOES_52_SEMANAS + 1 : i + 1]
                preco = float(velas[i].fechamento)
                minima = float(min(v.minima for v in janela))
                maxima = float(max(v.maxima for v in janela))

                lpa_v1, _ = dados.lpa_em(simbolo, dia, usar_ttm=False)
                lpa_v2, fonte_v2 = dados.lpa_em(simbolo, dia, usar_ttm=True)
                recomendacoes = {
                    VERSAO_REGRA: sinal_v1(preco, lpa_v1, minima, maxima),
                    VERSAO_REGRA_V2: recomendar_v2(
                        EntradaV2(preco, lpa_v2, dados.juros_em(dia), dados.ipca_12m_em(dia),
                                  posicao_no_range(preco, minima, maxima), fonte_v2)
                    ).recomendacao,
                }
                if all(r == "SEM_DADOS" for r in recomendacoes.values()):
                    meses_sem_balanco += 1
                    continue
                sinais += 1
                com_sinal.add(simbolo)
                primeira = min(primeira or dia, dia)
                ultima = max(ultima or dia, dia)
                periodo = "CALIBRACAO" if dia <= self._corte else "TESTE"

                for horizonte in self._horizontes:
                    if i + horizonte >= len(serie):
                        continue
                    entrada, saida = serie[i + 1].data, serie[i + horizonte].data
                    base = avaliar(
                        dia, None, serie[i : i + horizonte + 1], horizonte,
                        carteira=carteira_entre(entrada, saida), cdi_diario=cdi_entre(entrada, saida),
                    )
                    if base is None:
                        continue
                    for versao, recomendacao in recomendacoes.items():
                        if recomendacao == "SEM_DADOS":
                            continue
                        sentido = direcao(recomendacao)
                        resultado = replace(
                            base, acerto=None if sentido == 0 else (base.retorno_liquido * sentido) > 0
                        )
                        avaliacoes.append(Avaliacao(simbolo, versao, periodo, recomendacao, resultado))
                        contagem[versao, recomendacao] += 1

        nunca = sorted(set(series) - com_sinal)
        if nunca:
            observacoes.append(f"Sem nenhum balanço entregue no período (fora do placar): {', '.join(nunca)}")
        if meses_sem_balanco:
            observacoes.append(f"{meses_sem_balanco} combinações ativo-mês sem balanço já entregue ficaram sem sinal")
        suspeitas = sum(a.resultado.evento_suspeito for a in avaliacoes)
        if avaliacoes:
            observacoes.append(
                f"{suspeitas} de {len(avaliacoes)} janelas com salto de {LIMIAR_SALTO_SUSPEITO:.0%} ou mais "
                "(provável desdobramento) ficaram fora do placar"
            )
        observacoes.append("Preço sem proventos; universo de hoje aplicado ao passado (viés de sobrevivência).")

        placar = agregar(avaliacoes)
        self._validar(placar, avaliacoes)
        for linha in placar:
            db.execute(
                text(
                    "INSERT INTO backtest_placar (execucao_id, versao_regra, periodo, recomendacao, horizonte, "
                    "avaliados, acertos, taxa_base, retorno_medio, excesso_medio_cdi, excesso_medio_carteira) "
                    "VALUES (:e, :versao, :periodo, :recomendacao, :horizonte, :avaliados, :acertos, :taxa_base, "
                    ":retorno_medio, :excesso_cdi, :excesso_carteira)"
                ),
                {"e": execucao_id, **linha},
            )
        parametros = {
            "versoes": [VERSAO_REGRA, VERSAO_REGRA_V2],
            "frequencia": "primeiro pregao de cada mes",
            "horizontes_pregoes": list(self._horizontes),
            "custo_ida_e_volta": str(CUSTO_IDA_E_VOLTA_PADRAO),
            "fonte_preco": "B3 COTAHIST (bruto)",
            "fonte_lucro": "CVM pela DT_RECEB (v1: anual; v2: TTM quando houver)",
            "ativos": sorted(series),
            "sinais_por_recomendacao": {f"{v} {r}": n for (v, r), n in sorted(contagem.items())},
        }
        db.execute(
            text(
                "UPDATE backtest_execucao SET status='SUCESSO', finalizado_em=NOW(), inicio_periodo=:i, "
                "fim_periodo=:f, ativos=:a, sinais=:s, parametros_json=:p, observacoes=:o WHERE id=:id"
            ),
            {"i": primeira, "f": ultima, "a": len(series), "s": sinais,
             "p": json.dumps(parametros, ensure_ascii=False), "o": "\n".join(observacoes), "id": execucao_id},
        )
        _registrar_rotina(db, "SUCESSO", len(placar))
        return f"ativos={len(series)} sinais={sinais} avaliacoes={len(avaliacoes)} linhas={len(placar)}"

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
    (mesmas janelas para as duas versoes), invertida para venda."""
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
        })
    return linhas


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
    parser = argparse.ArgumentParser(description="Backtest walk-forward das regras v1 e v2")
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
