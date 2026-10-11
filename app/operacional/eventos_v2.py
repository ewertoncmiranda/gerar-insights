"""Eventos operacional.*.v2 (OPRV2-INS-6): snapshot-ticker, consenso-sinais, tese-explicada,
timeline-ativo e alerta-ux, validados pelos contratos v2 da infra (`contracts/operacional/*.v2`).

Duas etapas, as duas sem comando proprio (DEC-AGT-1):
1. `registrar_saida` — chamada pela OperabilidadeV2 depois de salvar o snapshot e a timeline do
   ativo. Projeta cada conteudo no contrato v2 (so as propriedades que o schema declara), valida e
   grava em `evento_operacional_v2` (V30) **so o que mudou** desde o ultimo registro do ativo:
   snapshot/consenso/tese por hash do conteudo; item de timeline novo (eventId da timeline);
   alerta-ux quando o ativo passa a BLOQUEADO ou surge item CRITICO na timeline.
2. `publicar_pendentes_v2` — chamada no fim do diario (junto da publicacao v1): manda os pendentes
   para `sqs-eventos-operacionais-v2` dentro do envelope (mesmos campos do v1, schemaVersion "2") e
   marca `publicado_em`. Fila ausente: ficam pendentes para a proxima rotina.

Os contratos v2 descrevem o conteudo; o envelope e o mesmo do v1 (eventId para idempotencia,
correlationId por pregao, modo SIMULADO e aviso).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import date, datetime
from functools import lru_cache

from sqlalchemy import text

from app.operacional.eventos import AVISO, FUSO, PASTA_CONTRATOS, PayloadInvalido, correlacao

log = logging.getLogger("operacional")

FILA_V2_PADRAO = "sqs-eventos-operacionais-v2"
LOTE = 500
CONTRATOS = ("snapshot-ticker", "consenso-sinais", "tese-explicada", "timeline-ativo", "alerta-ux")
MOTIVOS_DE_LIQUIDEZ = {"SEM_METRICA_LIQUIDEZ", "HISTORICO_INSUFICIENTE", "VOLUME_BAIXO", "NEGOCIOS_BAIXOS",
                       "PRESENCA_BAIXA", "SPREAD_ALTO", "SPREAD_AUSENTE"}


def _puro(valor):
    return json.loads(json.dumps(valor, ensure_ascii=False, default=lambda v: v.isoformat()
                                 if isinstance(v, (date, datetime)) else float(v) if hasattr(v, "as_tuple") else str(v)))


@lru_cache(maxsize=1)
def _esquemas():
    from jsonschema import Draft202012Validator  # noqa: PLC0415
    from referencing import Registry, Resource  # noqa: PLC0415

    todos = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in PASTA_CONTRATOS.glob("*.schema.json")}
    registro = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in todos.values())
    comum = todos["comum.v2.schema.json"]["$defs"]
    validadores, propriedades = {}, {}
    for nome in CONTRATOS:
        schema = todos[f"{nome}.v2.schema.json"]
        validadores[nome] = Draft202012Validator(schema, registry=registro,
                                                 format_checker=Draft202012Validator.FORMAT_CHECKER)
        alvo = schema if "properties" in schema else comum[schema["$ref"].split("/")[-1]]
        propriedades[nome] = (alvo.get("properties") or {}, alvo.get("properties", {}).get("schemaVersion"))
    return validadores, propriedades


def projetar(contrato: str, conteudo: dict) -> dict:
    """So as propriedades declaradas no contrato (o snapshot interno tem campos a mais)."""
    props, versao = _esquemas()[1][contrato]
    saida = {k: v for k, v in _puro(conteudo).items() if k in props}
    if versao and "const" in versao:
        saida["schemaVersion"] = versao["const"]
    return saida


def validar(contrato: str, conteudo: dict) -> None:
    erros = list(_esquemas()[0][contrato].iter_errors(conteudo))
    if erros:
        raise PayloadInvalido(f"{contrato}: " + "; ".join(
            f"{'/'.join(map(str, e.path)) or '(raiz)'}: {e.message}" for e in erros[:5]))


def _hash(conteudo: dict) -> str:
    """Hash do conteudo sem a data do pregao: so muda quando o estado do ativo muda."""
    sem_data = {k: v for k, v in conteudo.items() if k not in ("dataPregao", "dataEvento")}
    return hashlib.sha256(json.dumps(sem_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _ultimo_hash(db, simbolo: str, contrato: str, versao: str) -> str | None:
    return db.execute(text(
        "SELECT conteudo_hash FROM evento_operacional_v2 WHERE simbolo = :s AND contrato = :c AND versao_regra = :v "
        "ORDER BY data_pregao DESC, id DESC LIMIT 1"), {"s": simbolo, "c": contrato, "v": versao}).scalar()


def _gravar(db, contrato: str, versao: str, data_pregao: date, simbolo: str | None, conteudo: dict,
            event_id: str | None = None) -> bool:
    validar(contrato, conteudo)
    h = _hash(conteudo)
    event_id = event_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"oprv2:{contrato}:{simbolo}:{data_pregao}:{h}"))
    return bool(db.execute(text(
        "INSERT IGNORE INTO evento_operacional_v2 (event_id, contrato, versao_regra, data_pregao, simbolo, "
        "conteudo_hash, payload_json) VALUES (:e, :c, :v, :d, :s, :h, :p)"),
        {"e": event_id, "c": contrato, "v": versao, "d": data_pregao, "s": simbolo, "h": h,
         "p": json.dumps(conteudo, ensure_ascii=False)}).rowcount)


def registrar_saida(db, snapshot: dict, timeline: list[dict], versao: str, data_pregao: date) -> int:
    """Grava na saida v2 o que mudou deste ativo neste pregao. Conteudo fora do contrato nao entra
    (erro no log); o snapshot ja foi salvo de qualquer forma."""
    simbolo = snapshot["simbolo"]
    gravados = 0
    try:
        anterior_snapshot = _ultimo_hash(db, simbolo, "snapshot-ticker", versao)
        status_anterior = db.execute(text(
            "SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.statusOperacional')) FROM evento_operacional_v2 "
            "WHERE simbolo = :s AND contrato = 'snapshot-ticker' AND versao_regra = :v "
            "ORDER BY data_pregao DESC, id DESC LIMIT 1"), {"s": simbolo, "v": versao}).scalar()
        for contrato, conteudo in (("snapshot-ticker", snapshot), ("consenso-sinais", snapshot["consenso"]),
                                   ("tese-explicada", snapshot["tese"])):
            projetado = projetar(contrato, conteudo)
            ultimo = anterior_snapshot if contrato == "snapshot-ticker" else _ultimo_hash(db, simbolo, contrato, versao)
            if _hash(projetado) != ultimo:
                gravados += _gravar(db, contrato, versao, data_pregao, simbolo, projetado)
        for item in timeline:
            projetado = projetar("timeline-ativo", {**item, "severidade": "ATENCAO" if item.get("severidade") == "ALERTA"
                                                     else item.get("severidade")})
            if projetado.get("eventId"):
                gravados += _gravar(db, "timeline-ativo", versao, data_pregao, simbolo, projetado,
                                    event_id=projetado["eventId"])
        gravados += _alertas(db, snapshot, timeline, versao, data_pregao, status_anterior)
    except PayloadInvalido as erro:
        log.error("Saida v2 de %s em %s fora do contrato, nao registrada: %s", simbolo, data_pregao, erro)
    return gravados


def _alertas(db, snapshot: dict, timeline: list[dict], versao: str, data_pregao: date, status_anterior) -> int:
    simbolo, gravados = snapshot["simbolo"], 0
    motivos = snapshot.get("motivosBloqueio") or []
    # So transicao real: o primeiro snapshot do ativo (sem anterior) nao gera alerta de bloqueio.
    if (snapshot.get("statusOperacional") == "BLOQUEADO" and status_anterior is not None
            and status_anterior != "BLOQUEADO"):
        categoria = "LIQUIDEZ" if any(m.get("codigo") in MOTIVOS_DE_LIQUIDEZ for m in motivos) else "DADO"
        alerta = {"id": f"{simbolo}:BLOQUEADO:{data_pregao}", "ativo": True, "severidade": "ATENCAO",
                  "categoria": categoria, "simbolo": simbolo, "titulo": "Ativo bloqueado para o operacional simulado",
                  "dataEvento": data_pregao.isoformat(), "createdAt": None,
                  "payload": {"motivosBloqueio": [{k: m.get(k) for k in ("codigo", "detalhe", "valor", "limite")
                                                   if m.get(k) is not None} for m in motivos]}}
        gravados += _gravar(db, "alerta-ux", versao, data_pregao, simbolo, _puro(alerta))
    for item in timeline:
        if item.get("severidade") == "CRITICO" and str(item.get("data")) == data_pregao.isoformat():
            alerta = {"id": f"{simbolo}:{item.get('tipo')}:{item.get('eventId')}", "ativo": True, "severidade": "CRITICO",
                      "categoria": item.get("categoria") or "RISCO", "simbolo": simbolo, "titulo": item.get("titulo"),
                      "dataEvento": str(item.get("data")), "createdAt": None, "payload": item.get("payload") or {}}
            gravados += _gravar(db, "alerta-ux", versao, data_pregao, simbolo, _puro(alerta))
    return gravados


def publicar_pendentes_v2(db, cliente_sqs=None, fila: str | None = None) -> dict:
    resumo = {"publicados": 0, "pendentes": 0}
    linhas = [dict(r) for r in db.execute(text(
        "SELECT * FROM evento_operacional_v2 WHERE publicado_em IS NULL ORDER BY id LIMIT :n"), {"n": LOTE}).mappings()]
    if not linhas:
        return resumo
    if cliente_sqs is None:
        from app.config.aws_config import AwsConfig  # noqa: PLC0415

        cliente_sqs = AwsConfig().get_sqs_client()
    try:
        url = cliente_sqs.get_queue_url(QueueName=fila or os.getenv("EVENTOS_OPERACIONAIS_V2_QUEUE", FILA_V2_PADRAO))["QueueUrl"]
    except Exception as erro:  # noqa: BLE001 - fila ainda nao provisionada: tenta na proxima rotina
        log.warning("Eventos v2: fila indisponivel (%s); %d ficam pendentes", erro, len(linhas))
        resumo["pendentes"] = len(linhas)
        return resumo
    agora = datetime.now(FUSO).isoformat(timespec="seconds")
    for linha in linhas:
        dados = json.loads(linha["payload_json"]) if isinstance(linha["payload_json"], (str, bytes)) else linha["payload_json"]
        envelope = {"schemaVersion": "2", "eventId": linha["event_id"],
                    "correlationId": correlacao(linha["versao_regra"], linha["data_pregao"]),
                    "evento": f"operacional.{linha['contrato']}.v2", "versao_regra": linha["versao_regra"],
                    "dataPregao": linha["data_pregao"].isoformat(), "emitidoEm": agora, "modo": "SIMULADO",
                    "aviso": AVISO, "dados": dados}
        try:
            cliente_sqs.send_message(QueueUrl=url, MessageBody=json.dumps(envelope, ensure_ascii=False),
                                     MessageAttributes={"evento": {"DataType": "String", "StringValue": envelope["evento"]},
                                                        "eventId": {"DataType": "String", "StringValue": linha["event_id"]}})
        except Exception as erro:  # noqa: BLE001
            log.warning("Eventos v2: falha ao publicar %s (%s); interrompido", linha["event_id"], erro)
            resumo["pendentes"] = len(linhas) - resumo["publicados"]
            break
        db.execute(text("UPDATE evento_operacional_v2 SET publicado_em = CURRENT_TIMESTAMP WHERE id = :i"),
                   {"i": linha["id"]})
        db.commit()
        resumo["publicados"] += 1
    return resumo
