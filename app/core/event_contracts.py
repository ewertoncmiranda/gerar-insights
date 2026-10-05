"""Contratos distribuídos pela infraestrutura; valida antes de abrir transação."""
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[2] / "contracts"
_VALIDATORS = {
    name: Draft202012Validator(json.loads((_ROOT / f"{name}.schema.json").read_text(encoding="utf-8")))
    for name in ("ativos", "series_historicas", "insight")
}


def preparar_evento(canal, payload):
    if not isinstance(payload, dict):
        raise ValueError("Evento deve ser um objeto JSON")
    payload = dict(payload)
    # Legado sem versão é v0. Novas versões desconhecidas nunca são interpretadas como v1.
    legado = "schemaVersion" not in payload
    if legado:
        payload["schemaVersion"] = "1.0"
    if legado and not payload.get("dedupKey"):
        if canal == "series_historicas":
            identidade = payload.get("results")
        else:
            identidade = {k: v for k, v in payload.items() if k not in ("schemaVersion", "dedupKey")}
        canonico = json.dumps(identidade, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload["dedupKey"] = hashlib.sha256(canonico.encode()).hexdigest()
    _VALIDATORS[canal].validate(payload)
    return payload


def validar_insight(payload):
    _VALIDATORS["insight"].validate(payload)
