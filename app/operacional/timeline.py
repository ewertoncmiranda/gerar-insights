"""Timeline operacional por ticker (OPRV2-INS-4)."""

from __future__ import annotations

from datetime import date, datetime

SEVERIDADE_PADRAO = {
    "POSICAO_ABERTA": "INFO",
    "POSICAO_FECHADA": "INFO",
    "BLOQUEIO_LIQUIDEZ": "ALERTA",
    "BLOQUEIO_DADO": "ALERTA",
    "DIARIO_AVALIADO": "INFO",
    "ALERTA_RISCO": "CRITICO",
}


def montar_timeline(eventos: list[dict]) -> list[dict]:
    vistos: set[tuple] = set()
    itens: list[dict] = []
    for evento in eventos:
        chave = (
            evento.get("event_id") or evento.get("eventId"),
            evento.get("tipo"),
            evento.get("simbolo"),
            str(evento.get("data_pregao") or evento.get("data")),
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        tipo = evento.get("tipo") or evento.get("categoria") or "EVENTO"
        payload = evento.get("payload") or evento.get("payload_json") or {}
        if isinstance(payload, str):
            payload = {"texto": payload}
        itens.append({
            "eventId": evento.get("event_id") or evento.get("eventId"),
            "simbolo": evento.get("simbolo"),
            "data": _iso(evento.get("data_pregao") or evento.get("data")),
            "tipo": tipo,
            "severidade": evento.get("severidade") or SEVERIDADE_PADRAO.get(tipo, "INFO"),
            "titulo": _titulo(tipo, payload),
            "payload": payload,
        })
    return sorted(itens, key=lambda i: (i["data"] or "", _ordem(i["severidade"]), i["tipo"]))


def _titulo(tipo: str, payload: dict) -> str:
    if tipo == "POSICAO_ABERTA":
        return "Posicao simulada aberta"
    if tipo == "POSICAO_FECHADA":
        return f"Posicao simulada fechada ({payload.get('motivo_saida') or 'motivo nao informado'})"
    if tipo.startswith("BLOQUEIO"):
        return "Sinal barrado por regra operacional"
    if tipo == "ALERTA_RISCO":
        return "Alerta de risco operacional"
    return tipo.replace("_", " ").title()


def _iso(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return str(valor)


def _ordem(severidade: str) -> int:
    return {"CRITICO": 0, "ALERTA": 1, "INFO": 2}.get(severidade, 3)
