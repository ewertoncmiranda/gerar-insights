from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


BRASILIA_TZ = timezone(timedelta(hours=-3))


@dataclass
class CandleDiario:
    simbolo: str
    data_pregao: date
    intervalo: str
    range_usado: str | None
    abertura: Decimal | None
    maxima: Decimal | None
    minima: Decimal | None
    fechamento: Decimal | None
    fechamento_ajustado: Decimal | None
    volume: int | None
    detalhes_json: dict


def extrair_candles(payload: dict) -> list[CandleDiario]:
    resultados = payload.get("results")
    if resultados is None and "data" in payload:
        resultados = [payload]
    if not isinstance(resultados, list):
        raise ValueError("Payload de serie historica sem lista results valida")

    candles = []
    for resultado in resultados:
        simbolo = resultado.get("symbol") or resultado.get("requestedSymbol")
        dados = resultado.get("data") or {}
        intervalo = dados.get("usedInterval") or "1d"
        range_usado = dados.get("usedRange")
        historico = dados.get("historicalDataPrice") or []

        if not simbolo:
            raise ValueError("Resultado de serie historica sem symbol")

        for item in historico:
            candles.append(_mapear_candle(simbolo, intervalo, range_usado, item))

    return candles


def _mapear_candle(simbolo: str, intervalo: str, range_usado: str | None, item: dict) -> CandleDiario:
    data_pregao = _resolver_data_pregao(item)
    return CandleDiario(
        simbolo=simbolo,
        data_pregao=data_pregao,
        intervalo=intervalo,
        range_usado=range_usado,
        abertura=_decimal(item.get("open")),
        maxima=_decimal(item.get("high")),
        minima=_decimal(item.get("low")),
        fechamento=_decimal(item.get("close")),
        fechamento_ajustado=_decimal(item.get("adjustedClose")),
        volume=_inteiro(item.get("volume")),
        detalhes_json={
            "date": item.get("date"),
            "dataFormatada": item.get("dataFormatada"),
        },
    )


def _resolver_data_pregao(item: dict) -> date:
    timestamp = item.get("date")
    if timestamp is not None:
        return datetime.fromtimestamp(int(timestamp), tz=BRASILIA_TZ).date()

    data_formatada = item.get("dataFormatada")
    if data_formatada:
        return datetime.strptime(data_formatada, "%d/%m/%Y").date()

    raise ValueError("Candle sem date ou dataFormatada")


def _decimal(valor):
    if valor is None:
        return None
    return Decimal(str(valor))


def _inteiro(valor):
    if valor is None:
        return None
    return int(Decimal(str(valor)))
