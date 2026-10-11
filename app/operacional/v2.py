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
import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy import bindparam, text

from app.operacional.elegibilidade import Elegibilidade
from app.operacional.repositorio import RepositorioOperacional
from app.operacional.snapshot import EntradaSnapshot, montar_snapshot
from app.operacional.servico import avaliar_pregao
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

    def setores(self, db) -> dict[str, str]:
        return dict(db.execute(text(
            "SELECT t.simbolo, COALESCE(g.grupo_setor, e.setor, 'SEM_SETOR') FROM cvm_ticker t "
            "LEFT JOIN cvm_empresa e ON e.cnpj = t.cnpj "
            "LEFT JOIN setor_grupo g ON g.setor_cvm = e.setor"
        )).all())

    def elegibilidades(self, db, data_pregao: date, versao: str) -> dict[str, Elegibilidade]:
        """Usa a mesma avaliacao oficial do diario; V2 nao recalcula liquidez/elegibilidade por fora."""
        _, itens = avaliar_pregao(
            db, data_pregao=data_pregao, versao=versao, repositorio=RepositorioOperacional())
        return {item.simbolo: item for item in itens}

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
            "WHERE versao_regra = :v AND status IN ('PENDENTE', 'ABERTA', 'FECHADA') "
            "AND id IN (SELECT MAX(id) FROM operacao_simulada WHERE versao_regra = :v GROUP BY simbolo)"
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
        status_sistema = snapshot.get("statusSistema") or snapshot.get("statusOperacional") or "NAO_OPERAVEL"
        db.execute(text(
            "INSERT INTO ticker_operacional_snapshot "
            "(simbolo, data_pregao, versao_regra, status_sistema, status_operacional, faixa_liquidez, "
            "setor_grupo, sinal_principal, sinal_tecnico, opiniao_ia, confianca_faixa, posicao_status, "
            "ultimo_evento_tipo, "
            "payload_json, consenso_json, tese_json, atualizado_em) "
            "VALUES (:simbolo, :data_pregao, :versao_regra, :status, :status_operacional, :liquidez, :setor, "
            ":sinal, :tecnico, :opiniao, :confianca, :posicao, :evento, :payload, :consenso, :tese, "
            "CURRENT_TIMESTAMP) "
            "ON DUPLICATE KEY UPDATE status_sistema = VALUES(status_sistema), "
            "status_operacional = VALUES(status_operacional), "
            "faixa_liquidez = VALUES(faixa_liquidez), setor_grupo = VALUES(setor_grupo), "
            "sinal_principal = VALUES(sinal_principal), "
            "sinal_tecnico = VALUES(sinal_tecnico), opiniao_ia = VALUES(opiniao_ia), "
            "confianca_faixa = VALUES(confianca_faixa), posicao_status = VALUES(posicao_status), "
            "ultimo_evento_tipo = VALUES(ultimo_evento_tipo), payload_json = VALUES(payload_json), "
            "consenso_json = VALUES(consenso_json), tese_json = VALUES(tese_json), atualizado_em = CURRENT_TIMESTAMP"
        ), {
            "simbolo": snapshot["simbolo"],
            "data_pregao": snapshot["dataPregao"],
            "versao_regra": snapshot["versaoRegra"],
            "status": status_sistema,
            "status_operacional": snapshot.get("statusOperacional"),
            "liquidez": snapshot["faixaLiquidez"],
            "setor": snapshot.get("setorGrupo"),
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
            "(event_id, simbolo, data_pregao, data_evento, versao_regra, ocorrido_em, tipo_evento, tipo, "
            "categoria, severidade, codigo, titulo, payload_json, criado_em) "
            "VALUES (:event_id, :simbolo, :data_evento, :data_evento, :versao_regra, :data_evento, :tipo, :tipo, "
            ":categoria, :severidade, :tipo, :titulo, :payload, CURRENT_TIMESTAMP)"
        ).bindparams(bindparam("payload"))
        for item in itens:
            event_id = item.get("eventId") or str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"opr-timeline:{simbolo}:{item['data']}:{item['tipo']}"))
            severidade = "ATENCAO" if item["severidade"] == "ALERTA" else item["severidade"]
            payload = {**item, "eventId": event_id, "versaoRegra": versao, "severidade": severidade}
            db.execute(comando, {
                "event_id": event_id,
                "simbolo": simbolo,
                "data_evento": item["data"],
                "versao_regra": versao,
                "tipo": item["tipo"],
                "categoria": item.get("categoria") or "EVENTO",
                "severidade": severidade,
                "titulo": item["titulo"],
                "payload": _json(payload),
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
        setores = self.repo.setores(db)
        elegibilidades = self.repo.elegibilidades(db, data_pregao, versao)
        insights = self.repo.insights(db, data_pregao)
        opinioes = self.repo.opinioes(db, data_pregao)
        posicoes = self.repo.posicoes(db, versao)
        eventos = self.repo.eventos(db, data_pregao, versao)
        curva = curva_real(self.repo.amostras_confianca(db, versao))

        simbolos = set(liquidez) | set(elegibilidades) | set(insights) | set(opinioes) | set(posicoes) | set(eventos)
        total = 0
        for simbolo in sorted(simbolos):
            evs = eventos.get(simbolo, [])
            timeline = montar_timeline(evs)
            elegibilidade = elegibilidades.get(simbolo)
            motivos = _motivos_da_elegibilidade(elegibilidade) or _motivos_bloqueio(evs, data_pregao)
            entrada = EntradaSnapshot(
                simbolo=simbolo,
                data_pregao=data_pregao,
                versao_regra=versao,
                status_sistema=status,
                status_operacional=_status_operacional_ticker(status, elegibilidade),
                setor_grupo=setores.get(simbolo),
                faixa_liquidez=elegibilidade.faixa if elegibilidade else _faixa_liquidez(liquidez.get(simbolo)),
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
                ressalvas_elegibilidade=_ressalvas_da_elegibilidade(elegibilidade),
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


def _status_operacional_ticker(status_sistema: str | None, elegibilidade: Elegibilidade | None) -> str:
    """Status do ticker, separado do status oficial do sistema no diario.

    O enum segue o contrato existente: bloqueios do ticker viram BLOQUEADO; quando o ticker esta apto,
    o status acompanha a trava global do diario (EM_OBSERVACAO ou PAPER_TRADING_ELEGIVEL).
    """
    if status_sistema in {"NAO_OPERAVEL", "BLOQUEADO"}:
        return status_sistema
    if elegibilidade is None:
        return "NAO_OPERAVEL"
    if not elegibilidade.elegivel:
        return "BLOQUEADO"
    if status_sistema in {"EM_OBSERVACAO", "PAPER_TRADING_ELEGIVEL"}:
        return status_sistema
    return "NAO_OPERAVEL"


def _motivos_da_elegibilidade(elegibilidade: Elegibilidade | None) -> list[dict]:
    if elegibilidade is None:
        return []
    return [asdict(motivo) for motivo in elegibilidade.bloqueios]


def _ressalvas_da_elegibilidade(elegibilidade: Elegibilidade | None) -> list[dict]:
    if elegibilidade is None:
        return []
    return [asdict(motivo) for motivo in elegibilidade.ressalvas]


def _motivos_bloqueio(eventos: list[dict], data_pregao: date) -> list[dict]:
    motivos = []
    for evento in eventos:
        if evento.get("tipo") not in {"BLOQUEIO_LIQUIDEZ", "BLOQUEIO_DADO"}:
            continue
        data_evento = evento.get("data_pregao") or evento.get("data")
        if isinstance(data_evento, date):
            data_evento = data_evento.isoformat()
        if str(data_evento or "")[:10] != data_pregao.isoformat():
            continue
        payload = evento.get("payload") or {}
        motivos.extend(payload.get("motivos") or [])
    return motivos
