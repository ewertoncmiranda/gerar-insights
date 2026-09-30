"""Preco ajustado por desdobramento, grupamento e bonificacao (LAC-INS-2). Puro.

O COTAHIST e bruto: num desdobramento 2:1 o preco cai 50% sem ninguem ter
vendido. O ajuste e feito NA LEITURA, nunca regravando o COTAHIST: todo
preco anterior a data de efeito de um evento e multiplicado pelo fator_preco
dele (1 / fator_acoes), acumulando os eventos posteriores. A serie fica na
escala de hoje, e retornos e fatores atravessam o evento sem salto.

So entram eventos de `evento_corporativo` (a data vem da marca ex do
COTAHIST; a proporcao, da composicao de capital, com confianca). A marca ex
sozinha nao ajusta nada.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TypeVar

# Abaixo disso o ETL nao tem certeza da proporcao: o evento fica fora do
# ajuste e a janela com o salto e descartada como antes (risco do plano).
CONFIANCA_MINIMA = Decimal("0.8")

# Todo campo em R$/acao (as dataclasses que nao tem o campo sao puladas);
# razoes como spread/preco_medio nao mudam, porque os dois lados escalam juntos.
CAMPOS_DE_PRECO = ("abertura", "maxima", "minima", "fechamento", "preco_medio", "oferta_compra", "oferta_venda")

T = TypeVar("T")


@dataclass(frozen=True)
class EventoCorporativo:
    simbolo: str
    data_efeito: date
    fator_preco: Decimal
    confianca: Decimal | None = None

    @property
    def confiavel(self) -> bool:
        return self.confianca is None or self.confianca >= CONFIANCA_MINIMA


def fator_acumulado(eventos: list[EventoCorporativo], dia: date) -> Decimal:
    """Produto dos fatores dos eventos com efeito DEPOIS de `dia`: o preco
    de `dia` vezes esse numero fica na escala de hoje."""
    fator = Decimal(1)
    for evento in eventos:
        if evento.confiavel and evento.data_efeito > dia:
            fator *= evento.fator_preco
    return fator


def ajustar(serie: list[T], eventos: list[EventoCorporativo]) -> list[T]:
    """Serie (dataclasses com `data` e campos de preco) com os precos
    anteriores a cada evento multiplicados pelo fator acumulado. Sem evento
    confiavel devolve a propria lista, sem copia."""
    eventos = [e for e in eventos if e.confiavel]
    if not eventos:
        return serie
    saida = []
    for item in serie:
        fator = fator_acumulado(eventos, item.data)
        if fator == 1:
            saida.append(item)
            continue
        mudancas = {
            campo: _vezes(getattr(item, campo), fator)
            for campo in CAMPOS_DE_PRECO
            if hasattr(item, campo) and getattr(item, campo) is not None
        }
        saida.append(replace(item, **mudancas))
    return saida


def _vezes(valor, fator: Decimal):
    """Mantem o tipo do campo: Decimal no avaliador, float nos fatores."""
    return valor * fator if isinstance(valor, Decimal) else valor * float(fator)


def datas_com_evento(eventos: list[EventoCorporativo]) -> set[date]:
    """Datas de efeito com evento confiavel: salto nessas datas nao e suspeito."""
    return {e.data_efeito for e in eventos if e.confiavel}
