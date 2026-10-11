"""Leitura para o operacional simulado (Plano OPR). Tabelas de outros escritores, SQL explicito:
`regra_operacional` e `ativo_liquidez_diaria` (V23; ETL), `indicador_fundamentalista`,
`evento_corporativo` e `comunicado_cvm` (ETL). Tudo filtrado por data <= pregao da decisao:
nenhuma consulta olha o futuro. Consultas em lote por pregao (uma por fonte), nao por ativo.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date

from sqlalchemy import text

from app.operacional.elegibilidade import FatosDoAtivo

COLUNAS_LIQUIDEZ = (
    "volume_financeiro_medio_21d", "volume_financeiro_medio_63d", "negocios_medio_63d", "presenca_63d",
    "spread_mediano_63d", "spread_estimado_63d", "atr14", "volatilidade_63d", "percentil_volatilidade", "dias_sem_preco_63d",
    "ajuste_serie",
)


class RegraNaoEncontrada(LookupError):
    pass


class RepositorioOperacional:
    def parametros_da_regra(self, db, versao_regra: str) -> dict:
        linha = db.execute(
            text("SELECT parametros_json FROM regra_operacional WHERE versao_regra = :v"), {"v": versao_regra}
        ).first()
        if linha is None:
            raise RegraNaoEncontrada(f"regra_operacional sem a versão {versao_regra!r} (V23 aplicada?)")
        valor = linha[0]
        return json.loads(valor) if isinstance(valor, (str, bytes)) else (valor or {})

    def ultimo_pregao_com_liquidez(self, db) -> date | None:
        return db.execute(text("SELECT MAX(data_pregao) FROM ativo_liquidez_diaria")).scalar()

    def liquidez_do_pregao(self, db, data_pregao: date) -> dict[str, dict]:
        linhas = db.execute(
            text(f"SELECT simbolo, {', '.join(COLUNAS_LIQUIDEZ)} FROM ativo_liquidez_diaria WHERE data_pregao = :d"),
            {"d": data_pregao},
        )
        return {s: dict(zip(COLUNAS_LIQUIDEZ, resto)) for s, *resto in linhas}

    def _pregoes_mercado(self, db, ate: date, quantidade: int = 40) -> list[date]:
        datas = [d for (d,) in db.execute(
            text("SELECT DISTINCT data_pregao FROM cotacao_b3_diaria WHERE data_pregao <= :d "
                 "ORDER BY data_pregao DESC LIMIT :n"), {"d": ate, "n": quantidade})]
        return sorted(datas)

    def _cnpj_por_simbolo(self, db) -> dict[str, str]:
        """Mesma precedencia do ETL: indicador, cadastro atual (cvm_ticker) e curadoria (V6) por cima."""
        mapa = dict(db.execute(text(
            "SELECT DISTINCT simbolo, cnpj FROM indicador_fundamentalista WHERE cnpj IS NOT NULL")).all())
        mapa.update(db.execute(text("SELECT simbolo, cnpj FROM cvm_ticker WHERE cnpj IS NOT NULL")).all())
        mapa.update(db.execute(text("SELECT simbolo, cnpj FROM ativo_identidade WHERE cnpj IS NOT NULL")).all())
        return mapa

    def fatos_do_pregao(self, db, data_pregao: date) -> dict[str, FatosDoAtivo]:
        """Ultima entrega de fundamento, ultimo evento corporativo e ultimo fato relevante por ativo."""
        # Fundamento e da empresa (CNPJ), nao do codigo: units (TAEE11) e outras classes (KLBN4)
        # herdam o da companhia. Por simbolo direto tambem, para ticker antigo sem cadastro atual.
        por_cnpj = dict(db.execute(text(
            "SELECT cnpj, MAX(data_entrega) FROM indicador_fundamentalista "
            "WHERE data_entrega <= :d AND cnpj IS NOT NULL GROUP BY cnpj"), {"d": data_pregao}).all())
        fundamento = dict(db.execute(text(
            "SELECT simbolo, MAX(data_entrega) FROM indicador_fundamentalista "
            "WHERE data_entrega <= :d GROUP BY simbolo"), {"d": data_pregao}).all())
        for simbolo, cnpj in self._cnpj_por_simbolo(db).items():
            entrega = por_cnpj.get(cnpj)
            if entrega and (fundamento.get(simbolo) is None or entrega > fundamento[simbolo]):
                fundamento[simbolo] = entrega
        evento = dict(db.execute(text(
            "SELECT simbolo, MAX(data_efeito) FROM evento_corporativo "
            "WHERE data_efeito <= :d GROUP BY simbolo"), {"d": data_pregao}).all())
        fato = dict(db.execute(text(
            "SELECT t.simbolo, MAX(c.data_entrega) FROM comunicado_cvm c JOIN cvm_ticker t ON t.cnpj = c.cnpj "
            "WHERE c.categoria = 'FATO_RELEVANTE' AND c.data_entrega <= :d GROUP BY t.simbolo"),
            {"d": data_pregao}).all())
        mercado = self._pregoes_mercado(db, data_pregao)

        def pregoes_desde(dia: date | None) -> int | None:
            """Pregoes do mercado depois de `dia` ate o pregao (0 = no proprio pregao)."""
            if dia is None or not mercado or dia < mercado[0]:
                return None  # mais antigo que a janela: nao e recente
            return len(mercado) - bisect_right(mercado, dia)

        simbolos = set(fundamento) | set(evento) | set(fato)
        return {
            s: FatosDoAtivo(
                ultima_entrega_fundamento=fundamento.get(s),
                ultimo_evento_corporativo=evento.get(s),
                ultimo_fato_relevante=fato.get(s),
                pregoes_desde_evento=pregoes_desde(evento.get(s)),
                pregoes_desde_fato=pregoes_desde(fato.get(s)),
            )
            for s in simbolos
        }
