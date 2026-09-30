"""Calculo mensal dos fatores (LAC-INS-3 a 7).

No primeiro pregao de cada mes, para cada papel do universo daquele ano
(universo.py, o mesmo do backtest):
  1. serie emendada pelo codigo canonico e ajustada por evento corporativo;
  2. fatores de preco, qualidade/valor e evento, so com o passado;
  3. percentil no universo e no grupo de setor;
  4. grava em fator_valor os codigos que existem em fator_definicao.
Depois, com o mes seguinte ja conhecido, os fatores de referencia do mes
(fator_mercado_mensal).
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from logging import Logger

from app.fatores import evento, mercado, percentis, preco, qualidade
from app.fatores.ajuste_preco import EventoCorporativo, ajustar
from app.fatores.fonte_proventos import FonteProventos
from app.fatores.preco import PregaoFator
from app.fatores.repositorio import RepositorioFatores
from app.external.database.cotahist_repository import RepositorioCotahist
from app.validacao.universo import universo_por_ano

VERSAO_MERCADO = "1"
# Caracteristica auxiliar do SMB: nao e fator gravado (nao esta em fator_definicao).
VALOR_MERCADO = "VALOR_MERCADO"


def emendar(series_por_codigo: dict[str, list[PregaoFator]], identidades: dict[str, tuple[str, bool]],
            universo: set[str]) -> dict[str, list[PregaoFator]]:
    """Serie por codigo CANONICO (ELET3 ate a troca, AXIA3 depois); na mesma data vence o canonico."""
    por_ativo: dict[str, dict[date, tuple[bool, PregaoFator]]] = defaultdict(dict)
    for codigo, serie in series_por_codigo.items():
        canonico, continuo = identidades.get(codigo, (codigo, True))
        if canonico not in universo or not continuo:
            continue
        e_canonico = codigo == canonico
        for p in serie:
            atual = por_ativo[canonico].get(p.data)
            if atual and atual[0] and not e_canonico:
                continue
            por_ativo[canonico][p.data] = (e_canonico, p)
    return {s: [p for _, p in sorted(d.values(), key=lambda x: x[1].data)] for s, d in por_ativo.items()}


@dataclass
class ResumoCalculo:
    meses: int = 0
    linhas_fator: int = 0
    linhas_mercado: int = 0


class CalculoDeFatores:
    def __init__(self, fabrica_de_sessao, logger: Logger, repositorio: RepositorioFatores | None = None):
        self._sessao = fabrica_de_sessao
        self._logger = logger
        self._repo = repositorio or RepositorioFatores()

    def calcular(self, desde: date, ate: date | None = None) -> ResumoCalculo:
        with self._sessao() as db:
            self._repo.exigir(db, "fator_valor", "fator_definicao", "fator_mercado_mensal")
            definicoes = self._repo.definicoes(db)
            identidades = RepositorioCotahist().identidades(db)
            universo_ano = universo_por_ano(db, identidades)
            universo = set().union(*universo_ano.values()) if universo_ano else set()
            codigos = universo | {s for s, (c, continuo) in identidades.items() if c in universo and continuo}

            brutas = emendar(self._repo.series(db, codigos), identidades, universo)
            eventos = self._repo.eventos_corporativos(db)
            ajustadas = {s: ajustar(serie, eventos.get(s, [])) for s, serie in brutas.items()}
            retornos = {s: preco.retornos_diarios(serie) for s, serie in ajustadas.items()}
            mercado_diario = preco.media_do_universo(retornos)

            balancos = self._repo.balancos(db)
            cnpj_de = self._repo.cnpj_por_simbolo(db)
            comunicados = self._repo.comunicados(db)
            grupos = self._repo.grupo_setor(db)
            proventos = FonteProventos.carregar(db, self._repo)
            cdi = self._repo.cdi_diario(db)
            datas_cdi = sorted(cdi)

            referencias = self._repo.primeiros_pregoes_do_mes(db, desde, ate)
            resumo = ResumoCalculo()
            caracteristicas_por_ref: dict[date, dict[str, dict[str, float]]] = {}
            for ref in referencias:
                membros = [s for s in universo_ano.get(ref.year, set()) if s in ajustadas]
                valores: dict[str, dict[str, float]] = {}
                for simbolo in membros:
                    valores[simbolo] = self._fatores_do_papel(
                        simbolo, ref, brutas[simbolo], ajustadas[simbolo], mercado_diario,
                        balancos.get(simbolo, []), proventos, comunicados.get(cnpj_de.get(simbolo, ""), []),
                    )
                caracteristicas_por_ref[ref] = valores
                linhas = self._linhas(ref, valores, grupos, definicoes)
                resumo.linhas_fator += self._repo.gravar_fatores(db, linhas)
                resumo.meses += 1
                db.commit()
                self._logger.info("Fatores de %s: %s papeis, %s linhas", ref, len(membros), len(linhas))

            resumo.linhas_mercado = self._fatores_de_mercado(db, referencias, caracteristicas_por_ref, ajustadas,
                                                             cdi, datas_cdi)
            db.commit()
            return resumo

    @staticmethod
    def _fatores_do_papel(simbolo, ref, bruta, ajustada, mercado_diario, balancos, proventos: FonteProventos,
                          comunicados) -> dict[str, float]:
        fatores = preco.calcular(ajustada, ref, mercado_diario)
        passado_bruto = [p for p in bruta if p.data < ref]
        preco_bruto = passado_bruto[-1].fechamento if passado_bruto else None
        fatores.update(qualidade.calcular(balancos, ref, preco_bruto, proventos.em_12_meses(simbolo, ref)))
        fatores.update(evento.calcular(comunicados, ref))
        atual = qualidade.vigente(balancos, ref)
        if preco_bruto and atual and atual.acoes:
            fatores[VALOR_MERCADO] = preco_bruto * atual.acoes
        return fatores

    @staticmethod
    def _linhas(ref: date, valores: dict[str, dict[str, float]], grupos: dict[str, str],
                definicoes: set[str]) -> list[dict]:
        por_codigo: dict[str, dict[str, float]] = defaultdict(dict)
        for simbolo, fatores in valores.items():
            for codigo, valor in fatores.items():
                if codigo in definicoes:
                    por_codigo[codigo][simbolo] = valor
        linhas = []
        for codigo, por_papel in por_codigo.items():
            no_universo = percentis.percentis(por_papel)
            no_setor = percentis.percentis_por_grupo(por_papel, grupos)
            for simbolo, valor in por_papel.items():
                linhas.append({"simbolo": simbolo, "data": ref, "codigo": codigo, "valor": valor,
                               "pu": no_universo.get(simbolo), "ps": no_setor.get(simbolo),
                               "grupo": grupos.get(simbolo)})
        return linhas

    def _fatores_de_mercado(self, db, referencias, caracteristicas, ajustadas, cdi, datas_cdi) -> int:
        linhas = []
        fechamentos = {s: {p.data: p.fechamento for p in serie} for s, serie in ajustadas.items()}
        for ref, proximo in zip(referencias, referencias[1:]):
            retorno = {}
            for simbolo in caracteristicas[ref]:
                entrada, saida = fechamentos[simbolo].get(ref), fechamentos[simbolo].get(proximo)
                if entrada and saida:
                    retorno[simbolo] = saida / entrada - 1
            i, j = bisect.bisect_left(datas_cdi, ref), bisect.bisect_left(datas_cdi, proximo)
            fator_cdi = 1.0
            for dia in datas_cdi[i:j]:
                fator_cdi *= 1 + cdi[dia] / 100
            cdi_mes = fator_cdi - 1 if j > i else None
            for f in mercado.fatores_do_mes(retorno, caracteristicas[ref], cdi_mes):
                linhas.append({"data": ref, "codigo": f.codigo, "versao": VERSAO_MERCADO, "retorno": f.retorno,
                               "n_long": f.n_long, "n_short": f.n_short})
        return self._repo.gravar_fatores_de_mercado(db, linhas)


# EventoCorporativo re-exportado para quem monta testes do servico.
__all__ = ["CalculoDeFatores", "EventoCorporativo", "ResumoCalculo", "emendar"]
