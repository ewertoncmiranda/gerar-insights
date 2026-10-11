"""Atualizacao da Operabilidade V2 dentro do diario operacional.

OPRV2-INS-1..4:
- snapshot por ticker;
- consenso de sinais;
- tese explicada;
- timeline operacional.

Sem comando proprio: chamado pela etapa existente do diario. Enquanto as
migrations V2 da infra nao existirem, a etapa faz no-op seguro.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import bindparam, text

from app.operacional.snapshot import EntradaSnapshot, montar_snapshot
from app.operacional.timeline import montar_timeline
from app.validacao.confianca import curva_real
from app.validacao.repositorio_diario import RepositorioDiario as RepositorioValidacao

log = logging.getLogger("operacional")


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def _obj(valor):
    if isinstance(valor, (str, bytes)):
        return json.loads(valor)
    return valor or {}


class RepositorioOperabilidadeV2:
    """SQL explicito: a infra/Flyway e dona das tabelas V2."""

    def tabelas_v2_disponiveis(self, db) -> bool:
        total = db.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() "
            "AND table_name IN ('ticker_operacional_snapshot', 'ticker_operacional_timeline')"
        )).scalar()
        return int(total or 0) == 2

    def status_do_pregao(self, db, data_pregao: date, versao: str) -> str | None:
        return db.execute(text(
            "SELECT status_sistema FROM diario_operacional "
            "WHERE data_pregao = :d AND versao_regra = :v ORDER BY id DESC LIMIT 1"
        ), {"d": data_pregao, "v": versao}).scalar()

    def liquidez(self, db, data_pregao: date) -> dict[str, dict]:
        linhas = db.execute(text(
            "SELECT simbolo, volume_financeiro_medio_63d, negocios_medio_63d, presenca_63d, "
            "spread_mediano_63d, spread_estimado_63d, atr14, volatilidade_63d, ajuste_serie "
            "FROM ativo_liquidez_diaria WHERE data_pregao = :d"
        ), {"d": data_pregao}).mappings()
        return {r["simbolo"]: dict(r) for r in linhas}

    def insights(self, db, data_pregao: date) -> dict[str, dict]:
        linhas = db.execute(text(
            "SELECT i.simbolo, i.recomendacao, i.detalhes_json FROM insight_acao i "
            "JOIN (SELECT simbolo, MAX(id) id FROM insight_acao "
            "      WHERE DATE(data_analise) <= :d AND recomendacao IS NOT NULL GROUP BY simbolo) u "
            "ON u.id = i.id"
        ), {"d": data_pregao}).mappings()
        saida = {}
        for r in linhas:
            detalhes = _obj(r["detalhes_json"])
            resumo = detalhes.get("resumo") or {}
            tecnico = detalhes.get("contexto_tecnico_serie") or {}
            v2 = detalhes.get("regra_v2") or detalhes.get("sinal_v2") or {}
            saida[r["simbolo"]] = {
                "sinal_principal": resumo.get("sinal_quantitativo") or resumo.get("recomendacao") or r["recomendacao"],
                "confianca_score": resumo.get("confianca_score"),
                "sinal_momentum": tecnico.get("sinal_momentum"),
                "sinal_reversao": tecnico.get("sinal_reversao"),
                "sinal_v2": v2.get("recomendacao") if isinstance(v2, dict) else None,
            }
        return saida

    def opinioes(self, db, data_pregao: date) -> dict[str, str]:
        linhas = db.execute(text(
            "SELECT simbolo, opiniao FROM opiniao_ia WHERE data_pregao <= :d "
            "ORDER BY data_pregao ASC, (origem = 'MODELO') ASC, criado_em ASC, id ASC"
        ), {"d": data_pregao})
        return {s: o for s, o in linhas}

    def posicoes(self, db, versao: str) -> dict[str, dict]:
        linhas = db.execute(text(
            "SELECT simbolo, status, data_entrada, data_decisao_entrada, data_saida, horizonte_pregoes, "
            "quantidade, motivo_entrada_json, motivo_saida_json FROM operacao_simulada "
            "WHERE versao_regra = :v AND status IN ('PENDENTE', 'ABERTA')"
        ), {"v": versao}).mappings()
        saida = {}
        for r in linhas:
            saida[r["simbolo"]] = {
                "status": r["status"],
                "dataEntrada": r["data_entrada"],
                "dataDecisaoEntrada": r["data_decisao_entrada"],
                "dataSaida": r["data_saida"],
                "horizontePregoes": r["horizonte_pregoes"],
                "quantidade": r["quantidade"],
                "motivoEntrada": _obj(r["motivo_entrada_json"]),
                "motivoSaida": _obj(r["motivo_saida_json"]),
            }
        return saida

    def eventos(self, db, data_pregao: date, versao: str) -> dict[str, list[dict]]:
        linhas = db.execute(text(
            "SELECT event_id, tipo, data_pregao, simbolo, payload_json FROM evento_operacional "
            "WHERE versao_regra = :v AND data_pregao <= :d "
            "AND data_pregao >= DATE_SUB(:d, INTERVAL 30 DAY) "
            "AND simbolo IS NOT NULL ORDER BY data_pregao, id"
        ), {"d": data_pregao, "v": versao}).mappings()
        saida: dict[str, list[dict]] = {}
        for r in linhas:
            evento = dict(r)
            evento["payload"] = _obj(evento.pop("payload_json"))
            saida.setdefault(evento["simbolo"], []).append(evento)
        return saida

    def amostras_confianca(self, db, versao: str):
        return RepositorioValidacao().amostras_confianca(db, versao_regra=versao)

    def salvar_snapshot(self, db, snapshot: dict) -> None:
        db.execute(text(
            "INSERT INTO ticker_operacional_snapshot "
            "(simbolo, data_pregao, versao_regra, status_operacional, faixa_liquidez, sinal_principal, "
            "sinal_tecnico, opiniao_ia, confianca_faixa, posicao_status, ultimo_evento_tipo, "
            "payload_json, consenso_json, tese_json, atualizado_em) "
            "VALUES (:simbolo, :data_pregao, :versao_regra, :status, :liquidez, :sinal, :tecnico, :opiniao, "
            ":confianca, :posicao, :evento, :payload, :consenso, :tese, CURRENT_TIMESTAMP) "
            "ON DUPLICATE KEY UPDATE status_operacional = VALUES(status_operacional), "
            "faixa_liquidez = VALUES(faixa_liquidez), sinal_principal = VALUES(sinal_principal), "
            "sinal_tecnico = VALUES(sinal_tecnico), opiniao_ia = VALUES(opiniao_ia), "
            "confianca_faixa = VALUES(confianca_faixa), posicao_status = VALUES(posicao_status), "
            "ultimo_evento_tipo = VALUES(ultimo_evento_tipo), payload_json = VALUES(payload_json), "
            "consenso_json = VALUES(consenso_json), tese_json = VALUES(tese_json), atualizado_em = CURRENT_TIMESTAMP"
        ), {
            "simbolo": snapshot["simbolo"],
            "data_pregao": snapshot["dataPregao"],
            "versao_regra": snapshot["versaoRegra"],
            "status": snapshot["statusOperacional"],
            "liquidez": snapshot["faixaLiquidez"],
            "sinal": snapshot["sinalPrincipal"],
            "tecnico": _json(snapshot["sinalTecnico"]),
            "opiniao": snapshot["opiniaoIa"],
            "confianca": snapshot["confiancaFaixa"],
            "posicao": (snapshot.get("posicao") or {}).get("status"),
            "evento": (snapshot.get("ultimoEvento") or {}).get("tipo"),
            "payload": _json(snapshot),
            "consenso": _json(snapshot["consenso"]),
            "tese": _json(snapshot["tese"]),
        })

    def salvar_timeline(self, db, simbolo: str, versao: str, itens: list[dict]) -> None:
        if not itens:
            return
        comando = text(
            "INSERT IGNORE INTO ticker_operacional_timeline "
            "(event_id, simbolo, data_evento, versao_regra, tipo, severidade, titulo, payload_json, criado_em) "
            "VALUES (:event_id, :simbolo, :data_evento, :versao_regra, :tipo, :severidade, :titulo, :payload, "
            "CURRENT_TIMESTAMP)"
        ).bindparams(bindparam("payload"))
        for item in itens:
            db.execute(comando, {
                "event_id": item["eventId"] or f"{simbolo}:{item['data']}:{item['tipo']}",
                "simbolo": simbolo,
                "data_evento": item["data"],
                "versao_regra": versao,
                "tipo": item["tipo"],
                "severidade": item["severidade"],
                "titulo": item["titulo"],
                "payload": _json(item),
            })


class OperabilidadeV2:
    def __init__(self, repositorio: RepositorioOperabilidadeV2 | None = None):
        self.repo = repositorio or RepositorioOperabilidadeV2()

    def atualizar_pregao(self, db, data_pregao: date, versao: str) -> int:
        if not self.repo.tabelas_v2_disponiveis(db):
            log.info("Operabilidade V2: tabelas ausentes; snapshot/timeline ignorados")
            return 0

        status = self.repo.status_do_pregao(db, data_pregao, versao)
        liquidez = self.repo.liquidez(db, data_pregao)
        insights = self.repo.insights(db, data_pregao)
        opinioes = self.repo.opinioes(db, data_pregao)
        posicoes = self.repo.posicoes(db, versao)
        eventos = self.repo.eventos(db, data_pregao, versao)
        curva = curva_real(self.repo.amostras_confianca(db, versao))

        simbolos = set(liquidez) | set(insights) | set(opinioes) | set(posicoes) | set(eventos)
        total = 0
        for simbolo in sorted(simbolos):
            evs = eventos.get(simbolo, [])
            timeline = montar_timeline(evs)
            motivos = _motivos_bloqueio(evs, posicoes.get(simbolo))
            entrada = EntradaSnapshot(
                simbolo=simbolo,
                data_pregao=data_pregao,
                versao_regra=versao,
                status_operacional=status,
                faixa_liquidez=_faixa_liquidez(liquidez.get(simbolo)),
                sinal_principal=(insights.get(simbolo) or {}).get("sinal_principal"),
                sinal_momentum=(insights.get(simbolo) or {}).get("sinal_momentum"),
                sinal_reversao=(insights.get(simbolo) or {}).get("sinal_reversao"),
                sinal_v2=(insights.get(simbolo) or {}).get("sinal_v2"),
                opiniao_ia=opinioes.get(simbolo),
                confianca_score=(insights.get(simbolo) or {}).get("confianca_score"),
                confianca_tem_evidencia=curva.tem_evidencia_real,
                posicao=posicoes.get(simbolo),
                ultimo_evento=timeline[-1] if timeline else None,
                motivos_bloqueio=motivos,
            )
            snapshot = montar_snapshot(entrada)
            self.repo.salvar_snapshot(db, snapshot)
            self.repo.salvar_timeline(db, simbolo, versao, timeline)
            total += 1
        log.info("Operabilidade V2: snapshots=%d data=%s", total, data_pregao)
        return total


def _faixa_liquidez(metricas: dict | None) -> str | None:
    if not metricas:
        return None
    volume = metricas.get("volume_financeiro_medio_63d")
    negocios = metricas.get("negocios_medio_63d")
    if volume is None or negocios is None:
        return None
    if float(volume) >= 5_000_000 and float(negocios) >= 1000:
        return "ALTA"
    if float(volume) >= 1_000_000 and float(negocios) >= 200:
        return "MEDIA"
    return "INSUFICIENTE"


def _motivos_bloqueio(eventos: list[dict], posicao: dict | None) -> list[dict]:
    motivos = []
    for evento in eventos:
        if evento.get("tipo") not in {"BLOQUEIO_LIQUIDEZ", "BLOQUEIO_DADO"}:
            continue
        payload = evento.get("payload") or {}
        motivos.extend(payload.get("motivos") or [])
    motivo_entrada = (posicao or {}).get("motivoEntrada") or {}
    elegibilidade = motivo_entrada.get("elegibilidade") or {}
    motivos.extend(elegibilidade.get("bloqueios") or [])
    return motivos
