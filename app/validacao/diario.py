"""Diario de sinais (paper trading).

Duas operacoes, pensadas para rodar todo dia util depois do fechamento:

  registrar  grava UM sinal por ativo para o pregao: o ultimo insight gerado
             entre a abertura desse pregao e a abertura do seguinte. Como o
             worker reprocessa cada ativo a cada ~30 s, esse e em geral o
             insight feito com o preco de fechamento - e os de fim de semana,
             feitos com o preco de sexta, contam para sexta.
  avaliar    para cada sinal com horizonte vencido, mede o resultado com o
             mesmo motor do backtest (avaliador.py) e grava em sinal_resultado.

Uso:
    python -m app.validacao.diario registrar [--data AAAA-MM-DD]
    python -m app.validacao.diario avaliar

Por que existe: e o unico teste que nao da para enganar. O backtest pode ter
viés que ninguem percebeu; o diario grava a previsao ANTES de o resultado
existir. Cada dia sem registro e evidencia perdida para sempre.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from logging import Logger

from app.validacao.avaliador import HORIZONTES_PREGOES, avaliar

# B3 em horario de Brasilia (UTC-3, sem horario de verao desde 2019); o banco
# grava data_analise em UTC. Abertura do pregao a vista: 10h.
FUSO_B3 = timezone(timedelta(hours=-3))
ABERTURA_B3 = time(10, 0)
BENCHMARK = "BOVA11"


def abertura_em_utc(dia: date) -> datetime:
    """10h de Brasilia no dia, em UTC ingenuo (como o banco grava)."""
    local = datetime.combine(dia, ABERTURA_B3, tzinfo=FUSO_B3)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def janela_do_sinal(pregao: date, proximo_pregao: date | None, agora_utc: datetime) -> tuple[datetime, datetime]:
    """[abertura do pregao, abertura do pregao seguinte) em UTC.

    Sem pregao seguinte conhecido (o registro roda na noite do proprio dia),
    o fim e agora: nao existe insight do futuro para pegar.
    """
    inicio = abertura_em_utc(pregao)
    fim = abertura_em_utc(proximo_pregao) if proximo_pregao else agora_utc
    return inicio, fim


def extrair_sinal(detalhes: dict) -> dict | None:
    """Campos do sinal a partir do detalhes_json do insight.

    Sem versao_regra o insight e anterior ao versionamento: nao da para saber
    qual regra o gerou, entao nao entra no diario.
    """
    versao = detalhes.get("versao_regra")
    if not versao:
        return None
    resumo = detalhes.get("resumo") or {}
    serie = detalhes.get("contexto_tecnico_serie") or {}
    return {
        "versao_regra": versao,
        "nivel_risco": resumo.get("nivel_risco"),
        "confianca_score": resumo.get("confianca_score"),
        "sinal_momentum": serie.get("sinal_momentum"),
        "sinal_reversao": serie.get("sinal_reversao"),
    }


@dataclass
class ResumoRegistro:
    data_pregao: date | None = None
    registrados: list[str] = field(default_factory=list)
    ja_existiam: list[str] = field(default_factory=list)
    sem_insight: list[str] = field(default_factory=list)
    sem_versao: list[str] = field(default_factory=list)


@dataclass
class ResumoAvaliacao:
    resultados_gravados: int = 0
    sinais_pendentes: int = 0


class DiarioDeSinais:
    def __init__(self, repositorio, fabrica_de_sessao, logger: Logger, horizontes=HORIZONTES_PREGOES):
        self._repo = repositorio
        self._sessao = fabrica_de_sessao
        self._logger = logger
        self._horizontes = tuple(horizontes)

    def registrar(self, data_pregao: date | None, agora_utc: datetime) -> ResumoRegistro:
        resumo = ResumoRegistro()
        with self._sessao() as db:
            if data_pregao is None:
                hoje_b3 = agora_utc.replace(tzinfo=timezone.utc).astimezone(FUSO_B3).date()
                data_pregao = self._repo.ultimo_pregao_ate(db, hoje_b3)
                if data_pregao is None:
                    self._logger.warning("Nenhum pregao em candle_diario; nada a registrar")
                    return resumo
            resumo.data_pregao = data_pregao

            # So ativo com candle neste dia: garante que foi dia de pregao e da
            # o fechamento oficial de referencia.
            fechamentos = self._repo.fechamentos_do_pregao(db, data_pregao)
            if not fechamentos:
                self._logger.warning("Sem candles em %s (nao foi pregao?); nada a registrar", data_pregao)
                return resumo

            inicio, fim = janela_do_sinal(
                data_pregao, self._repo.proximo_pregao(db, data_pregao), agora_utc
            )
            for simbolo in sorted(fechamentos):
                if simbolo == BENCHMARK:
                    continue
                insight = self._repo.ultimo_insight(db, simbolo, inicio, fim)
                if insight is None:
                    resumo.sem_insight.append(simbolo)
                    continue
                campos = extrair_sinal(insight["detalhes"])
                if campos is None:
                    resumo.sem_versao.append(simbolo)
                    continue
                novo = self._repo.inserir_sinal(
                    db,
                    {
                        **campos,
                        "simbolo": simbolo,
                        "data_pregao": data_pregao,
                        "recomendacao": insight["recomendacao"],
                        "preco_fechamento": fechamentos[simbolo],
                        "insight_id": insight["id"],
                    },
                )
                (resumo.registrados if novo else resumo.ja_existiam).append(simbolo)
            db.commit()
        return resumo

    def avaliar(self) -> ResumoAvaliacao:
        resumo = ResumoAvaliacao()
        with self._sessao() as db:
            pendentes = self._repo.sinais_com_horizonte_pendente(db, len(self._horizontes))
            if not pendentes:
                return resumo

            desde = min(s["data_pregao"] for s in pendentes)
            cdi = self._repo.cdi_diario(db, desde)
            benchmark = self._repo.serie_de_precos(db, BENCHMARK, desde)
            series: dict[str, list] = {}

            for sinal in pendentes:
                serie = series.get(sinal["simbolo"])
                if serie is None:
                    serie = self._repo.serie_de_precos(db, sinal["simbolo"], desde)
                    series[sinal["simbolo"]] = serie
                feitos = self._repo.horizontes_avaliados(db, sinal["id"])
                ainda_falta = False
                for horizonte in self._horizontes:
                    if horizonte in feitos:
                        continue
                    resultado = avaliar(
                        sinal["data_pregao"], sinal["recomendacao"], serie, horizonte,
                        benchmark=benchmark, cdi_diario=cdi,
                    )
                    if resultado is None:
                        ainda_falta = True
                        continue
                    self._repo.inserir_resultado(db, sinal["id"], resultado)
                    resumo.resultados_gravados += 1
                if ainda_falta:
                    resumo.sinais_pendentes += 1
            db.commit()
        return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diario de sinais (paper trading)")
    parser.add_argument("comando", choices=["registrar", "avaliar"])
    parser.add_argument("--data", type=date.fromisoformat, help="pregao a registrar (padrao: o ultimo)")
    argumentos = parser.parse_args(argv)

    # Importes tardios: o modulo continua testavel sem banco configurado.
    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.validacao.repositorio_diario import RepositorioDiario

    logger = setup_logger()
    diario = DiarioDeSinais(RepositorioDiario(), ConfigDatabase().session, logger)
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if argumentos.comando == "registrar":
        r = diario.registrar(argumentos.data, agora_utc)
        logger.info(
            "Diario %s | registrados=%d %s | ja existiam=%d | sem insight=%s | sem versao de regra=%s",
            r.data_pregao, len(r.registrados), r.registrados, len(r.ja_existiam),
            r.sem_insight, r.sem_versao,
        )
    else:
        r = diario.avaliar()
        logger.info(
            "Avaliacao do diario | resultados gravados=%d | sinais ainda pendentes=%d",
            r.resultados_gravados, r.sinais_pendentes,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
