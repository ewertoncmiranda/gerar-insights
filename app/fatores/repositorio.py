"""Unica porta dos fatores (Plano LAC) para o banco. SQL explicito: as
tabelas sao do ETL e da V16.

Tolerante a V16 ausente: tabela ou coluna que ainda nao existe devolve
vazio (sem ajuste, sem provento da DVA, sem oferta), e gravar em tabela
ausente falha com mensagem clara em vez de gravar pela metade.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text

from app.fatores.ajuste_preco import EventoCorporativo
from app.fatores.preco import PregaoFator
from app.fatores.proventos_contabeis import MARCAS_DE_PROVENTO, ProventoContabil
from app.fatores.qualidade import Balanco


class TabelaAusente(RuntimeError):
    pass


class RepositorioFatores:
    def __init__(self) -> None:
        self._colunas: dict[str, set[str]] = {}

    # --- esquema ---------------------------------------------------------

    def colunas(self, db, tabela: str) -> set[str]:
        if tabela not in self._colunas:
            self._colunas[tabela] = {
                c for (c,) in db.execute(
                    text("SELECT column_name FROM information_schema.columns "
                         "WHERE table_schema = DATABASE() AND table_name = :t"),
                    {"t": tabela},
                )
            }
        return self._colunas[tabela]

    def existe(self, db, tabela: str) -> bool:
        return bool(self.colunas(db, tabela))

    def exigir(self, db, *tabelas: str) -> None:
        faltando = [t for t in tabelas if not self.existe(db, t)]
        if faltando:
            raise TabelaAusente(
                f"Tabela(s) {', '.join(faltando)} ausente(s): aplique a migracao V16 (Plano LAC) antes."
            )

    # --- leituras ----------------------------------------------------------

    def eventos_corporativos(self, db) -> dict[str, list[EventoCorporativo]]:
        if not self.existe(db, "evento_corporativo"):
            return {}
        saida: dict[str, list[EventoCorporativo]] = defaultdict(list)
        for simbolo, dia, fator, confianca in db.execute(text(
            "SELECT simbolo, data_efeito, fator_preco, confianca FROM evento_corporativo ORDER BY data_efeito"
        )):
            saida[simbolo].append(EventoCorporativo(
                simbolo, dia, Decimal(str(fator)), None if confianca is None else Decimal(str(confianca))))
        return dict(saida)

    def datas_ex_de_provento(self, db) -> dict[str, list[date]]:
        if "marca_ex" not in self.colunas(db, "cotacao_b3_diaria"):
            return {}
        saida: dict[str, list[date]] = defaultdict(list)
        for simbolo, dia, marca in db.execute(text(
            "SELECT simbolo, data_pregao, marca_ex FROM cotacao_b3_diaria WHERE marca_ex IS NOT NULL"
        )):
            if marca in MARCAS_DE_PROVENTO:
                saida[simbolo].append(dia)
        return dict(saida)

    def cnpj_por_simbolo(self, db) -> dict[str, str]:
        mapa = {s: c for s, c in db.execute(text("SELECT DISTINCT simbolo, cnpj FROM indicador_fundamentalista"))}
        if self.existe(db, "cvm_ticker"):
            for s, c in db.execute(text("SELECT simbolo, cnpj FROM cvm_ticker")):
                mapa.setdefault(s, c)
        return mapa

    def isin_por_simbolo(self, db) -> dict[str, str]:
        if "isin" not in self.colunas(db, "cvm_ticker"):
            return {}
        return {
            simbolo: isin
            for simbolo, isin in db.execute(text("SELECT simbolo, isin FROM cvm_ticker WHERE isin IS NOT NULL"))
        }

    def proventos_contabeis(self, db) -> dict[str, list[ProventoContabil]]:
        if not self.existe(db, "provento_contabil"):
            return {}
        saida: dict[str, list[ProventoContabil]] = defaultdict(list)
        for cnpj, tipo, ini, fim, entrega, por_acao in db.execute(text(
            "SELECT cnpj, tipo_doc, dt_ini_exerc, dt_fim_exerc, data_entrega, por_acao FROM provento_contabil"
        )):
            saida[cnpj].append(ProventoContabil(tipo, ini, fim, entrega,
                                                None if por_acao is None else Decimal(str(por_acao))))
        return dict(saida)

    def definicoes(self, db) -> set[str]:
        if not self.existe(db, "fator_definicao"):
            return set()
        return {c for (c,) in db.execute(text("SELECT codigo FROM fator_definicao WHERE ativo"))}

    def grupo_setor(self, db) -> dict[str, str]:
        """simbolo -> grupo de setor (cvm_ticker/indicador -> cvm_empresa.setor -> setor_grupo)."""
        if not self.existe(db, "setor_grupo"):
            return {}
        grupos = {s: g for s, g in db.execute(text("SELECT setor_cvm, grupo_setor FROM setor_grupo"))}
        setor_por_cnpj = {c: s for c, s in db.execute(text("SELECT cnpj, setor FROM cvm_empresa WHERE setor IS NOT NULL"))}
        return {
            simbolo: grupos[setor_por_cnpj[cnpj]]
            for simbolo, cnpj in self.cnpj_por_simbolo(db).items()
            if cnpj in setor_por_cnpj and setor_por_cnpj[cnpj] in grupos
        }

    def balancos(self, db) -> dict[str, list[Balanco]]:
        novas = ("ativo_total", "ativo_circulante", "passivo_circulante", "lucro_bruto")
        existentes = self.colunas(db, "indicador_fundamentalista")
        extras = ", ".join(c if c in existentes else f"NULL AS {c}" for c in novas)
        saida: dict[str, list[Balanco]] = defaultdict(list)
        for linha in db.execute(text(
            "SELECT simbolo, periodo, tipo_periodo, data_entrega, COALESCE(lucro_liquido_controlador, lucro_liquido), "
            "patrimonio_liquido, receita_liquida, ebit, divida_bruta, caixa_equivalentes, fluxo_caixa_operacional, "
            f"acoes_ex_tesouraria, lpa, vpa, {extras} FROM indicador_fundamentalista WHERE data_entrega IS NOT NULL"
        )):
            simbolo, periodo, tipo, entrega, *numeros = linha
            valores = [None if v is None else float(v) for v in numeros]
            saida[simbolo].append(Balanco(periodo, tipo, entrega, *valores))
        return dict(saida)

    def comunicados(self, db) -> dict[str, list[tuple[str, date]]]:
        saida: dict[str, list[tuple[str, date]]] = defaultdict(list)
        for cnpj, categoria, entrega in db.execute(text(
            "SELECT cnpj, categoria, data_entrega FROM comunicado_cvm "
            "WHERE categoria IN ('FATO_RELEVANTE', 'PROVENTOS')"
        )):
            saida[cnpj].append((categoria, entrega))
        return dict(saida)

    def series(self, db, codigos: set[str]) -> dict[str, list[PregaoFator]]:
        """Serie BRUTA por codigo negociado, com os campos que existirem."""
        existentes = self.colunas(db, "cotacao_b3_diaria")
        opcionais = [c if c in existentes else f"NULL AS {c}"
                     for c in ("preco_medio", "melhor_oferta_compra", "melhor_oferta_venda")]
        saida: dict[str, list[PregaoFator]] = defaultdict(list)
        if not codigos:
            return {}
        for simbolo, dia, fech, vol, medio, compra, venda in db.execute(
            text(
                "SELECT simbolo, data_pregao, fechamento, volume_financeiro, " + ", ".join(opcionais) +
                " FROM cotacao_b3_diaria WHERE simbolo IN :codigos AND fechamento > 0 ORDER BY data_pregao"
            ).bindparams(bindparam("codigos", expanding=True)),
            {"codigos": sorted(codigos)},
        ):
            saida[simbolo].append(PregaoFator(dia, float(fech), _f(vol), _f(medio), _f(compra), _f(venda)))
        return dict(saida)

    def primeiros_pregoes_do_mes(self, db, desde: date, ate: date | None = None) -> list[date]:
        return [d for (d,) in db.execute(text(
            "SELECT MIN(data_pregao) FROM cotacao_b3_diaria WHERE data_pregao >= :d AND data_pregao <= :a "
            "GROUP BY YEAR(data_pregao), MONTH(data_pregao) ORDER BY 1"
        ), {"d": desde, "a": ate or date.max})]

    def cdi_diario(self, db) -> dict[date, float]:
        return {d: float(v) for d, v in db.execute(text(
            "SELECT data, valor FROM indice_macro WHERE codigo_serie = 'CDI' AND valor IS NOT NULL"
        ))}

    # --- escritas ----------------------------------------------------------

    def gravar_fatores(self, db, linhas: list[dict]) -> int:
        self.exigir(db, "fator_valor", "fator_definicao")
        if not linhas:
            return 0
        db.execute(text(
            "INSERT INTO fator_valor (simbolo, data_referencia, fator_codigo, valor, percentil_universo, "
            "percentil_setor, grupo_setor) VALUES (:simbolo, :data, :codigo, :valor, :pu, :ps, :grupo) "
            "ON DUPLICATE KEY UPDATE valor = VALUES(valor), percentil_universo = VALUES(percentil_universo), "
            "percentil_setor = VALUES(percentil_setor), grupo_setor = VALUES(grupo_setor), calculado_em = NOW()"
        ), linhas)
        return len(linhas)

    def gravar_fatores_de_mercado(self, db, linhas: list[dict]) -> int:
        self.exigir(db, "fator_mercado_mensal")
        if not linhas:
            return 0
        db.execute(text(
            "INSERT INTO fator_mercado_mensal (data_referencia, fator_codigo, versao_calculo, retorno, "
            "n_ativos_long, n_ativos_short) VALUES (:data, :codigo, :versao, :retorno, :n_long, :n_short) "
            "ON DUPLICATE KEY UPDATE retorno = VALUES(retorno), n_ativos_long = VALUES(n_ativos_long), "
            "n_ativos_short = VALUES(n_ativos_short), calculado_em = NOW()"
        ), linhas)
        return len(linhas)

    def fatores_gravados(self, db, codigos: list[str], desde: date) -> dict[tuple[str, date], dict[str, float]]:
        """(simbolo, data_referencia) -> {codigo: percentil_universo} dos fatores pedidos."""
        self.exigir(db, "fator_valor")
        saida: dict[tuple[str, date], dict[str, float]] = defaultdict(dict)
        for simbolo, dia, codigo, percentil in db.execute(
            text(
                "SELECT simbolo, data_referencia, fator_codigo, percentil_universo FROM fator_valor "
                "WHERE fator_codigo IN :codigos AND data_referencia >= :d AND percentil_universo IS NOT NULL"
            ).bindparams(bindparam("codigos", expanding=True)),
            {"codigos": codigos, "d": desde},
        ):
            saida[(simbolo, dia)][codigo] = float(percentil)
        return dict(saida)

    def fatores_de_mercado(self, db, versao: str) -> dict[date, dict[str, float]]:
        if not self.existe(db, "fator_mercado_mensal"):
            return {}
        saida: dict[date, dict[str, float]] = defaultdict(dict)
        for dia, codigo, retorno in db.execute(text(
            "SELECT data_referencia, fator_codigo, retorno FROM fator_mercado_mensal WHERE versao_calculo = :v"
        ), {"v": versao}):
            saida[dia][codigo] = float(retorno)
        return dict(saida)


def _f(valor) -> float | None:
    return None if valor is None else float(valor)
