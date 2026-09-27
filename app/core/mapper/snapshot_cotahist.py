"""Adaptador: preco oficial (COTAHIST) + lucro da CVM -> o mesmo payload que
a BRAPI entrega.

Com isso a camada Base reaproveita inteiro o pipeline de analise
(MarketSnapshot.from_payload -> FinancialAnalyzerService) sem nenhuma regra
duplicada: muda so a origem do dado, nao a analise.
"""

from __future__ import annotations

from datetime import date

from app.external.database.cotahist_repository import PREGOES_52_SEMANAS, PregaoOficial


def payload_de_cotahist(
    simbolo: str, serie: list[PregaoOficial], lpa: float | None, dia: date
) -> dict | None:
    """Payload no formato BRAPI para o pregao `dia`; None se o ativo nao negociou nele."""
    indice = next((i for i, p in enumerate(serie) if p.data == dia), None)
    if indice is None:
        return None
    hoje = serie[indice]
    anterior = serie[indice - 1] if indice > 0 else None
    janela = serie[max(0, indice - PREGOES_52_SEMANAS + 1) : indice + 1]
    preco = float(hoje.fechamento)
    return {
        "symbol": simbolo,
        "regularMarketPrice": preco,
        "regularMarketOpen": float(hoje.abertura),
        "regularMarketDayHigh": float(hoje.maxima),
        "regularMarketDayLow": float(hoje.minima),
        "regularMarketPreviousClose": float(anterior.fechamento) if anterior else None,
        "regularMarketVolume": hoje.volume,
        "fiftyTwoWeekLow": float(min(p.minima for p in janela)),
        "fiftyTwoWeekHigh": float(max(p.maxima for p in janela)),
        "earningsPerShare": lpa,
        "priceEarnings": preco / lpa if lpa else None,
        "marketCap": None,
        # Marca a origem e o pregao: o diario de sinais casa o insight pelo
        # pregao do preco, nao pela hora em que a analise rodou.
        "fontePreco": "B3_COTAHIST",
        "dataPregaoReferencia": dia.isoformat(),
    }
