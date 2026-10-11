"""Publicacao dos eventos operacional.*.v1 (OPR-INS-7; contratos da OPR-INFRA-2).

O diario grava cada evento em `evento_operacional` (fila de saida, `publicado_em` NULL). Aqui cada
evento pendente vira o payload do contrato — montado das tabelas da V23, nao do rascunho gravado —,
e validado contra o JSON Schema de `contracts/operacional/` (copiado da infra por
`sincronizar-contratos.mjs`); so entao vai para a fila SQS `sqs-eventos-operacionais` e ganha
`publicado_em`. Sem conhecer Telegram nem painel: quem consome a fila e problema dos consumidores.

- Payload invalido: nao publica, registra o erro e o evento continua pendente (o defeito e de codigo).
- Fila fora do ar ou inexistente: para e tenta de novo na proxima rotina (nada se perde).
- Tipos sem contrato (BLOQUEIO_*, STATUS_ALTERADO) ficam so como trilha de auditoria.
Roda dentro do diario operacional (start unico, DEC-AGT-1); sem comando proprio.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import bindparam, text

from app.config.settings import Settings

log = logging.getLogger("operacional")

FILA_PADRAO = "sqs-eventos-operacionais"
AVISO = "Operacao simulada (paper trading): nao e ordem nem recomendacao de investimento."
FUSO = timezone(timedelta(hours=-3))
LOTE = 200
PASTA_CONTRATOS = Path(__file__).resolve().parents[2] / "contracts" / "operacional"

CONTRATO_DO_TIPO = {
    "POSICAO_ABERTA": "posicao-aberta",
    "POSICAO_FECHADA": "posicao-fechada",
    "DIARIO_AVALIADO": "diario-avaliado",
    "SINAL_GERADO": "sinal-gerado",
    "ALERTA_RISCO": "alerta-risco",
}
_CAMPOS_ABERTA = ("simbolo", "setor_grupo", "horizonte_pregoes", "data_decisao_entrada", "data_entrada",
                  "preco_entrada", "quantidade", "valor_entrada", "atr_entrada", "stop_inicial",
                  "faixa_liquidez_entrada", "custos_entrada")
_CAMPOS_FECHADA = ("simbolo", "horizonte_pregoes", "data_entrada", "data_saida", "preco_entrada", "preco_saida",
                   "quantidade", "motivo_saida", "custos_entrada", "custos_saida", "resultado_bruto",
                   "resultado_pos_custos", "imposto_estimado", "resultado_pos_imposto_estimado")
_CAMPOS_DIARIO = ("patrimonio", "caixa", "exposicao", "posicoes_abertas", "operacoes_abertas_dia",
                  "operacoes_fechadas_dia", "retorno_bruto_dia", "retorno_liquido_dia", "retorno_liquido_acumulado",
                  "cdi_acumulado", "cdi_liquido_ir_acumulado", "excesso_sobre_cdi_liquido", "drawdown",
                  "drawdown_maximo", "violacoes_liquidez", "status_sistema")


class PayloadInvalido(ValueError):
    pass


def _json_puro(valor):
    """Decimal -> numero, data -> ISO; o resto como veio."""
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() and valor.as_tuple().exponent >= 0 else float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json_puro(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json_puro(v) for v in valor]
    return valor


def _objeto(valor) -> dict:
    if isinstance(valor, (str, bytes)):
        valor = json.loads(valor)
    return valor or {}


@lru_cache(maxsize=1)
def _validadores() -> dict:
    """Um validador por contrato, com os $ref para comum/status resolvidos pelo $id dos arquivos."""
    from jsonschema import Draft202012Validator  # noqa: PLC0415
    from referencing import Registry, Resource  # noqa: PLC0415

    esquemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in PASTA_CONTRATOS.glob("*.schema.json")}
    registro = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in esquemas.values())
    return {nome.removesuffix(".v1.schema.json"): Draft202012Validator(s, registry=registro,
                                                                       format_checker=Draft202012Validator.FORMAT_CHECKER)
            for nome, s in esquemas.items() if nome.removesuffix(".v1.schema.json") in CONTRATO_DO_TIPO.values()}


def validar(contrato: str, payload: dict) -> None:
    erros = sorted(_validadores()[contrato].iter_errors(payload), key=lambda e: list(e.path))
    if erros:
        raise PayloadInvalido("; ".join(f"{'/'.join(map(str, e.path)) or '(raiz)'}: {e.message}" for e in erros[:5]))


def correlacao(versao: str, data_pregao: date) -> str:
    """Todos os eventos do mesmo pregao e versao de regra compartilham o correlationId."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"opr:{versao}:{data_pregao.isoformat()}"))


def _dados_operacao(db, evento: dict) -> dict:
    op = db.execute(text("SELECT * FROM operacao_simulada WHERE id = :i"), {"i": evento["operacao_id"]}).mappings().first()
    if op is None:
        raise PayloadInvalido(f"operacao {evento['operacao_id']} nao existe")
    if evento["tipo"] == "POSICAO_ABERTA":
        return {"operacao_id": op["id"], **{c: op[c] for c in _CAMPOS_ABERTA},
                "motivo_entrada": _objeto(op["motivo_entrada_json"])}
    detalhe = _objeto(op["motivo_saida_json"]) or {"motivo": op["motivo_saida"]}
    return {"operacao_id": op["id"], **{c: op[c] for c in _CAMPOS_FECHADA}, "motivo_saida_detalhe": detalhe}


def _dados_diario(db, evento: dict) -> dict:
    linha = db.execute(text("SELECT * FROM diario_operacional WHERE versao_regra = :v AND data_pregao = :d"),
                       {"v": evento["versao_regra"], "d": evento["data_pregao"]}).mappings().first()
    if linha is None:
        raise PayloadInvalido(f"diario {evento['data_pregao']} nao existe")
    anterior = db.execute(text(
        "SELECT status_sistema FROM diario_operacional WHERE versao_regra = :v AND data_pregao < :d "
        "ORDER BY data_pregao DESC LIMIT 1"), {"v": evento["versao_regra"], "d": evento["data_pregao"]}).scalar()
    avaliados = db.execute(text(
        "SELECT COUNT(*) FROM diario_operacional WHERE versao_regra = :v AND data_pregao <= :d"),
        {"v": evento["versao_regra"], "d": evento["data_pregao"]}).scalar()
    motivos = _objeto(linha["motivos_status_json"])
    # OPR-INS-6 grava a lista [{codigo, descricao}]; antes dela, o diario guarda so um texto de coleta.
    lista = motivos if isinstance(motivos, list) else (
        motivos.get("motivos") if isinstance(motivos.get("motivos"), list)
        else [{"codigo": "COLETA_EM_ANDAMENTO", "descricao": str(motivos.get("motivo") or "coleta em andamento")}])
    return {**{c: linha[c] for c in _CAMPOS_DIARIO}, "pregoes_avaliados": int(avaliados or 0),
            "status_anterior": anterior, "motivos_status": lista}


def montar_payload(db, evento: dict, agora: datetime | None = None) -> tuple[str, dict]:
    """(contrato, payload validado) de uma linha de `evento_operacional`."""
    contrato = CONTRATO_DO_TIPO[evento["tipo"]]
    if evento["tipo"] in ("POSICAO_ABERTA", "POSICAO_FECHADA"):
        dados = _dados_operacao(db, evento)
    elif evento["tipo"] == "DIARIO_AVALIADO":
        dados = _dados_diario(db, evento)
    else:  # SINAL_GERADO / ALERTA_RISCO: o rascunho gravado ja e o `dados` do contrato
        dados = _objeto(evento["payload_json"])
    payload = {
        "schemaVersion": "1", "eventId": evento["event_id"],
        "correlationId": evento["correlation_id"] or correlacao(evento["versao_regra"], evento["data_pregao"]),
        "evento": f"operacional.{contrato}.v1", "versao_regra": evento["versao_regra"],
        "dataPregao": evento["data_pregao"].isoformat(),
        "emitidoEm": (agora or datetime.now(FUSO)).isoformat(timespec="seconds"),
        "modo": "SIMULADO", "aviso": AVISO, "dados": _json_puro(dados),
    }
    validar(contrato, payload)
    return contrato, payload


def publicar_pendentes(db, cliente_sqs=None, fila: str | None = None) -> dict:
    """Publica os eventos com contrato ainda sem `publicado_em`, em ordem. Devolve a contagem."""
    resumo = {"publicados": 0, "invalidos": 0, "pendentes": 0}
    eventos = [dict(e) for e in db.execute(text(
        "SELECT * FROM evento_operacional WHERE publicado_em IS NULL AND tipo IN :tipos ORDER BY id LIMIT :n"
    ).bindparams(bindparam("tipos", expanding=True)),
        {"tipos": list(CONTRATO_DO_TIPO), "n": LOTE}).mappings()]
    if not eventos:
        return resumo
    if cliente_sqs is None:
        from app.config.aws_config import AwsConfig  # noqa: PLC0415

        cliente_sqs = AwsConfig().get_sqs_client()
    try:
        url = cliente_sqs.get_queue_url(QueueName=fila or Settings().eventos_operacionais_queue or FILA_PADRAO)["QueueUrl"]
    except Exception as erro:  # noqa: BLE001 - fila ainda nao provisionada ou LocalStack fora: tenta na proxima rotina
        log.warning("Eventos operacionais: fila indisponivel (%s); %d ficam pendentes", erro, len(eventos))
        resumo["pendentes"] = len(eventos)
        return resumo
    for evento in eventos:
        try:
            contrato, payload = montar_payload(db, evento)
        except PayloadInvalido as erro:
            resumo["invalidos"] += 1
            log.error("Evento %s (%s) fora do contrato, nao publicado: %s", evento["event_id"], evento["tipo"], erro)
            continue
        try:
            cliente_sqs.send_message(
                QueueUrl=url, MessageBody=json.dumps(payload, ensure_ascii=False),
                MessageAttributes={"evento": {"DataType": "String", "StringValue": payload["evento"]},
                                   "eventId": {"DataType": "String", "StringValue": payload["eventId"]}})
        except Exception as erro:  # noqa: BLE001 - fila caiu no meio: o resto fica para a proxima rotina
            log.warning("Eventos operacionais: falha ao publicar %s (%s); interrompido", evento["event_id"], erro)
            resumo["pendentes"] = len(eventos) - resumo["publicados"] - resumo["invalidos"]
            break
        db.execute(text("UPDATE evento_operacional SET publicado_em = CURRENT_TIMESTAMP, correlation_id = :c "
                        "WHERE id = :i"), {"c": payload["correlationId"], "i": evento["id"]})
        db.commit()
        resumo["publicados"] += 1
    return resumo
