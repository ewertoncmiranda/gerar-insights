"""Tese explicada da Operabilidade V2 (OPRV2-INS-3)."""

from __future__ import annotations

AVISO_SIMULACAO = (
    "Simulacao quantitativa para estudo. Nao e recomendacao de investimento, "
    "ordem, consultoria individual ou garantia de resultado."
)


def montar_tese(snapshot: dict, consenso: dict) -> dict:
    positivos: list[dict] = []
    negativos: list[dict] = []
    riscos: list[dict] = []
    invalidadores: list[dict] = []
    dados_ausentes: list[dict] = []

    if consenso.get("direcaoAnalitica") == "POSITIVA":
        positivos.append(_item("SINAL_ANALITICO_POSITIVO", "Sinais agregados favorecem o ativo.", "MEDIA"))
    elif consenso.get("direcaoAnalitica") == "NEGATIVA":
        negativos.append(_item("SINAL_ANALITICO_NEGATIVO", "Sinais agregados desfavorecem o ativo.", "MEDIA"))

    if snapshot.get("faixaLiquidez") == "ALTA":
        positivos.append(_item("LIQUIDEZ_ALTA", "Liquidez operacional em faixa alta.", "BAIXA"))
    elif snapshot.get("faixaLiquidez") in {"MEDIA", "INSUFICIENTE"}:
        riscos.append(_item("LIQUIDEZ_LIMITADA", "Liquidez limita tamanho, custo ou execucao simulada.", "MEDIA"))

    for motivo in snapshot.get("motivosBloqueio") or []:
        codigo = motivo.get("codigo") or "BLOQUEIO_OPERACIONAL"
        destino = dados_ausentes if "DADO" in codigo or "FUNDAMENTO" in codigo else invalidadores
        destino.append(_item(codigo, motivo.get("detalhe") or motivo.get("descricao") or "Bloqueio operacional.", "ALTA"))

    if snapshot.get("confiancaFaixa") == "NAO_CALIBRADA":
        riscos.append(_item(
            "CONFIANCA_NAO_CALIBRADA",
            "Score de confianca ainda nao tem curva real suficiente; nao trate como probabilidade.",
            "MEDIA",
        ))

    if snapshot.get("ultimoEvento"):
        riscos.append(_item("EVENTO_RECENTE", "Ha evento recente na timeline; revisar antes de interpretar o sinal.", "MEDIA"))

    invalidadores.extend([
        _item("PERDA_LIQUIDEZ", "Perda persistente de liquidez invalida a tese operacional.", "ALTA"),
        _item("MUDANCA_SINAL", "Mudanca para sinal negativo ou sem base invalida entrada simulada.", "ALTA"),
        _item("EVENTO_RELEVANTE", "Fato relevante ou ajuste de serie sem explicacao invalida a leitura automatica.", "ALTA"),
    ])

    return {
        "aviso": AVISO_SIMULACAO,
        "positivos": positivos,
        "negativos": negativos,
        "riscos": riscos,
        "invalidadores": invalidadores,
        "dadosAusentes": dados_ausentes,
    }


def _item(codigo: str, descricao: str, severidade: str) -> dict:
    return {"codigo": codigo, "descricao": descricao, "severidade": severidade}
