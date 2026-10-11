"""Leitura e escrita do diario operacional (OPR-INS-4). Escreve em `operacao_simulada`,
`diario_operacional` e `evento_operacional` (V23; este worker e o escritor unico). Le cotacao,
opiniao, setor, CDI e fatos relevantes de outros escritores, sempre com data <= pregao.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text

JANELA_OPINIAO = 5  # pregoes: opiniao mais velha que isso nao sustenta entrada nem saida


def _j(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


class RepositorioDiario:
    # ---- leitura -------------------------------------------------------------------------------
    def pregoes_mercado(self, db) -> list[date]:
        return [d for (d,) in db.execute(text("SELECT DISTINCT data_pregao FROM cotacao_b3_diaria ORDER BY data_pregao"))]

    def ultimo_diario(self, db, versao: str) -> dict | None:
        linha = db.execute(text(
            "SELECT data_pregao, capital_inicial, patrimonio, caixa, cdi_acumulado, drawdown_maximo, "
            "(SELECT MIN(data_pregao) FROM diario_operacional WHERE versao_regra = :v) AS inicio, "
            "(SELECT MAX(patrimonio) FROM diario_operacional WHERE versao_regra = :v) AS pico "
            "FROM diario_operacional WHERE versao_regra = :v ORDER BY data_pregao DESC LIMIT 1"), {"v": versao}).mappings().first()
        return dict(linha) if linha else None

    def primeiro_pregao_possivel(self, db) -> date | None:
        """Primeiro pregao com liquidez calculada e alguma opiniao gravada ate ele."""
        return db.execute(text(
            "SELECT GREATEST((SELECT MIN(data_pregao) FROM ativo_liquidez_diaria), "
            "(SELECT MIN(data_pregao) FROM opiniao_ia))")).scalar()

    def ultimo_pregao_com_liquidez(self, db) -> date | None:
        return db.execute(text("SELECT MAX(data_pregao) FROM ativo_liquidez_diaria")).scalar()

    def cotacoes(self, db, data_pregao: date, simbolos: set[str]) -> dict[str, dict]:
        if not simbolos:
            return {}
        comando = text("SELECT simbolo, abertura, maxima, fechamento FROM cotacao_b3_diaria "
                       "WHERE data_pregao = :d AND simbolo IN :s").bindparams(bindparam("s", expanding=True))
        return {s: {"abertura": a, "maxima": m, "fechamento": f}
                for s, a, m, f in db.execute(comando, {"d": data_pregao, "s": sorted(simbolos)})}

    def ultimo_fechamento(self, db, data_pregao: date, simbolos: set[str]) -> dict[str, Decimal]:
        if not simbolos:
            return {}
        comando = text(
            "SELECT c.simbolo, c.fechamento FROM cotacao_b3_diaria c JOIN ("
            " SELECT simbolo, MAX(data_pregao) d FROM cotacao_b3_diaria WHERE data_pregao <= :d AND simbolo IN :s "
            " GROUP BY simbolo) u ON u.simbolo = c.simbolo AND u.d = c.data_pregao").bindparams(bindparam("s", expanding=True))
        return dict(db.execute(comando, {"d": data_pregao, "s": sorted(simbolos)}).all())

    def opinioes(self, db, data_pregao: date, desde: date) -> dict[tuple[str, int], str]:
        """Opiniao mais recente por (ativo, horizonte) entre `desde` e o pregao; MODELO antes de REGRA."""
        linhas = db.execute(text(
            "SELECT simbolo, horizonte_pregoes, opiniao FROM opiniao_ia WHERE data_pregao BETWEEN :i AND :d "
            "ORDER BY data_pregao ASC, (origem = 'MODELO') ASC, criado_em ASC, id ASC"), {"i": desde, "d": data_pregao})
        return {(s, h): o for s, h, o in linhas}  # o ultimo de cada chave vence

    def setores(self, db) -> dict[str, str]:
        return dict(db.execute(text(
            "SELECT t.simbolo, COALESCE(g.grupo_setor, e.setor, 'SEM_SETOR') FROM cvm_ticker t "
            "LEFT JOIN cvm_empresa e ON e.cnpj = t.cnpj LEFT JOIN setor_grupo g ON g.setor_cvm = e.setor")).all())

    def cdi_do_dia(self, db, data_pregao: date) -> Decimal:
        """Taxa diaria em fracao (a serie guarda % ao dia); sem dado no dia, a ultima conhecida."""
        valor = db.execute(text(
            "SELECT valor FROM indice_macro WHERE codigo_serie = 'CDI' AND data <= :d ORDER BY data DESC LIMIT 1"),
            {"d": data_pregao}).scalar()
        return Decimal(str(valor or 0)) / Decimal(100)

    def fatos_relevantes(self, db, data_pregao: date, simbolos: set[str]) -> dict[str, list[date]]:
        if not simbolos:
            return {}
        comando = text(
            "SELECT t.simbolo, c.data_entrega FROM comunicado_cvm c JOIN cvm_ticker t ON t.cnpj = c.cnpj "
            "WHERE c.categoria = 'FATO_RELEVANTE' AND c.data_entrega <= :d "
            "AND c.data_entrega >= DATE_SUB(:d, INTERVAL 200 DAY) AND t.simbolo IN :s").bindparams(bindparam("s", expanding=True))
        saida: dict[str, list[date]] = {}
        for s, d in db.execute(comando, {"d": data_pregao, "s": sorted(simbolos)}):
            saida.setdefault(s, []).append(d)
        return saida

    def liquidez_recente(self, db, data_pregao: date, simbolos: set[str], pregoes: int) -> dict[str, list[dict]]:
        """Ultimas `pregoes` linhas de liquidez de cada ativo ate o pregao (mais recente primeiro)."""
        if not simbolos:
            return {}
        comando = text(
            "SELECT simbolo, data_pregao, volume_financeiro_medio_63d, negocios_medio_63d, presenca_63d, "
            "spread_mediano_63d FROM ativo_liquidez_diaria WHERE data_pregao <= :d AND simbolo IN :s "
            "AND data_pregao >= DATE_SUB(:d, INTERVAL 30 DAY) ORDER BY simbolo, data_pregao DESC").bindparams(bindparam("s", expanding=True))
        saida: dict[str, list[dict]] = {}
        for s, d, v, n, p, sp in db.execute(comando, {"d": data_pregao, "s": sorted(simbolos)}):
            lista = saida.setdefault(s, [])
            if len(lista) < pregoes:
                lista.append({"volume_financeiro_medio_63d": v, "negocios_medio_63d": n, "presenca_63d": p,
                              "spread_mediano_63d": sp})
        return saida

    def operacoes_em_curso(self, db, versao: str) -> list[dict]:
        ops = [dict(r) for r in db.execute(text(
            "SELECT * FROM operacao_simulada WHERE versao_regra = :v AND status IN ('PENDENTE','ABERTA') "
            "ORDER BY id"), {"v": versao}).mappings()]
        for op in ops:
            for campo in ("motivo_entrada_json", "motivo_saida_json"):
                if isinstance(op.get(campo), (str, bytes)):
                    op[campo] = json.loads(op[campo])
        return ops

    # ---- escrita -------------------------------------------------------------------------------
    def inserir_pendente(self, db, versao: str, op: dict) -> int:
        resultado = db.execute(text(
            "INSERT IGNORE INTO operacao_simulada (versao_regra, simbolo, setor_grupo, horizonte_pregoes, status, "
            "data_decisao_entrada, quantidade, atr_entrada, faixa_liquidez_entrada, motivo_entrada_json) "
            "VALUES (:v, :simbolo, :setor, :horizonte, 'PENDENTE', :data, :quantidade, :atr, :faixa, :motivo)"),
            {"v": versao, **op, "motivo": _j(op["motivo"])})
        return resultado.rowcount

    def atualizar(self, db, op_id: int, campos: dict) -> None:
        if "motivo_saida_json" in campos and not isinstance(campos["motivo_saida_json"], str):
            campos = {**campos, "motivo_saida_json": _j(campos["motivo_saida_json"])}
        db.execute(text(f"UPDATE operacao_simulada SET {', '.join(f'{c} = :{c}' for c in campos)} WHERE id = :id"),
                   {**campos, "id": op_id})

    def gravar_diario(self, db, versao: str, linha: dict) -> None:
        colunas = ["versao_regra", *linha]
        db.execute(text(f"INSERT INTO diario_operacional ({', '.join(colunas)}) "
                        f"VALUES ({', '.join(':' + c for c in colunas)})"),
                   {"versao_regra": versao, **{k: (_j(v) if isinstance(v, (dict, list)) else v) for k, v in linha.items()}})

    def evento(self, db, versao: str, tipo: str, data_pregao: date, payload: dict, simbolo: str | None = None,
               operacao_id: int | None = None, correlacao: str | None = None) -> None:
        """Fila de saida dos eventos operacional.*.v1 (publicacao: OPR-INS-7)."""
        db.execute(text(
            "INSERT INTO evento_operacional (event_id, correlation_id, tipo, versao_regra, data_pregao, simbolo, "
            "operacao_id, payload_json) VALUES (:e, :c, :t, :v, :d, :s, :o, :p)"),
            {"e": str(uuid.uuid4()), "c": correlacao, "t": tipo, "v": versao, "d": data_pregao, "s": simbolo,
             "o": operacao_id, "p": _j(payload)})
