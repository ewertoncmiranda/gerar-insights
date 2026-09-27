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

from app.core.analysis.regra_v2 import VERSAO_REGRA_V2, EntradaV2, posicao_no_range, recomendar_v2
from app.validacao.avaliador import HORIZONTES_PREGOES, avaliar
from app.validacao.proventos import codigo_emissor

# B3 em horario de Brasilia (UTC-3, sem horario de verao desde 2019); o banco
# grava data_analise em UTC. Abertura do pregao a vista: 10h.
FUSO_B3 = timezone(timedelta(hours=-3))
ABERTURA_B3 = time(10, 0)


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


def sinal_v2_em_sombra(detalhes: dict, fechamento: float, dados, simbolo: str, dia: date) -> dict:
    """Regra v2 aplicada ao mesmo pregao, com os dados como eram conhecidos
    no dia: fechamento oficial, faixa de 52 semanas do insight v1, LPA pela
    data de entrega na CVM, CDI e IPCA ja publicados."""
    snapshot = detalhes.get("snapshot_mercado") or {}
    lpa, fonte = dados.lpa_em(simbolo, dia)
    saida = recomendar_v2(
        EntradaV2(
            preco=fechamento,
            lpa=lpa,
            juros_anual_percent=dados.juros_em(dia),
            ipca_12m_percent=dados.ipca_12m_em(dia),
            posicao_52w=posicao_no_range(fechamento, snapshot.get("minima_52w"), snapshot.get("maxima_52w")),
            fonte_lpa=fonte,
        )
    )
    return {"recomendacao": saida.recomendacao, "detalhe": saida.como_dict()}


@dataclass
class ResumoRegistro:
    data_pregao: date | None = None
    registrados: list[str] = field(default_factory=list)
    sombra_v2: list[str] = field(default_factory=list)
    sombra_v2_sem_dados: list[str] = field(default_factory=list)
    ja_existiam: list[str] = field(default_factory=list)
    sem_insight: list[str] = field(default_factory=list)
    sem_versao: list[str] = field(default_factory=list)


@dataclass
class ResumoAvaliacao:
    resultados_gravados: int = 0
    sinais_pendentes: int = 0


class DiarioDeSinais:
    def __init__(self, repositorio, fabrica_de_sessao, logger: Logger, horizontes=HORIZONTES_PREGOES,
                 carregar_dados=None):
        """carregar_dados(db) -> DadosPontoNoTempo; None desliga a sombra v2."""
        self._carregar_dados = carregar_dados
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
            dados = self._carregar_dados(db) if self._carregar_dados else None
            for simbolo in sorted(fechamentos):
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

                if dados is None:
                    continue
                sombra = sinal_v2_em_sombra(
                    insight["detalhes"], float(fechamentos[simbolo]), dados, simbolo, data_pregao
                )
                if sombra["recomendacao"] == "SEM_DADOS":
                    resumo.sombra_v2_sem_dados.append(simbolo)
                    continue
                self._repo.inserir_sinal(
                    db,
                    {
                        "versao_regra": VERSAO_REGRA_V2,
                        "nivel_risco": None,
                        "confianca_score": None,
                        "sinal_momentum": campos.get("sinal_momentum"),
                        "sinal_reversao": campos.get("sinal_reversao"),
                        "simbolo": simbolo,
                        "data_pregao": data_pregao,
                        "recomendacao": sombra["recomendacao"],
                        "preco_fechamento": fechamentos[simbolo],
                        "insight_id": insight["id"],
                    },
                )
                resumo.sombra_v2.append(f"{simbolo}:{sombra['recomendacao']}")
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
            # Uma consulta so: a mesma carteira serve de serie do proprio
            # sinal e de regua (media simples) para todos os sinais.
            carteira = self._repo.series_da_carteira(db, desde)
            proventos_por_emissor = self._repo.proventos_por_emissor(db)

            for sinal in pendentes:
                serie = carteira.get(sinal["simbolo"], [])
                feitos = self._repo.horizontes_avaliados(db, sinal["id"])
                ainda_falta = False
                for horizonte in self._horizontes:
                    if horizonte in feitos:
                        continue
                    resultado = avaliar(
                        sinal["data_pregao"], sinal["recomendacao"], serie, horizonte,
                        carteira=carteira, cdi_diario=cdi,
                        proventos=proventos_por_emissor.get(codigo_emissor(sinal["simbolo"]), {}),
                        proventos_carteira=proventos_por_emissor,
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
    from app.validacao.ponto_no_tempo import DadosPontoNoTempo
    from app.validacao.repositorio_diario import RepositorioDiario

    logger = setup_logger()
    diario = DiarioDeSinais(
        RepositorioDiario(), ConfigDatabase().session, logger, carregar_dados=DadosPontoNoTempo.carregar
    )
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if argumentos.comando == "registrar":
        r = diario.registrar(argumentos.data, agora_utc)
        logger.info(
            "Diario %s | registrados=%d %s | ja existiam=%d | sem insight=%s | sem versao de regra=%s",
            r.data_pregao, len(r.registrados), r.registrados, len(r.ja_existiam),
            r.sem_insight, r.sem_versao,
        )
        logger.info(
            "Sombra v2 (%s) | registrados=%d %s | sem dados (LPA, juros)=%s",
            VERSAO_REGRA_V2, len(r.sombra_v2), r.sombra_v2, r.sombra_v2_sem_dados,
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
