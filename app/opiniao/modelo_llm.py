"""Contrato com o modelo de linguagem: prompt, schema da resposta, validacao e provedor Ollama.

O provedor e uma porta (`ProvedorLLM`): hoje so ha o Ollama (container local, perfil `ia` do
compose); trocar de modelo ou de provedor e configuracao. A resposta so vale depois do
validador: schema, opiniao dentro do conjunto permitido, risco igual ao calculado, cada
justificativa citando uma evidencia real e nenhum numero que nao esteja no dossie.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol

from app.opiniao.regras import (
    NEGATIVO,
    OPINIOES,
    POSITIVO,
    RISCOS,
    SEM_BASE,
    DossieDeHorizonte,
    Evidencia,
)

NOME_DO_HORIZONTE = {21: "curto (cerca de 1 mês, 21 pregões)",
                     63: "médio (cerca de 3 meses, 63 pregões)",
                     126: "longo (cerca de 6 meses, 126 pregões)"}

PALAVRAS_PROIBIDAS = ("garantido", "garantida", "certeza", "sem risco", "não tem como perder",
                      "imperdível", "compre", "venda agora", "vai subir", "vai cair",
                      "bom investimento", "boa oportunidade", "oportunidade de")

LIMITE_LEITURA = 200
LIMITE_INVALIDA = 160
MAXIMO_DE_EVIDENCIAS_NO_PEDIDO = 8
MAXIMO_DE_JUSTIFICATIVAS = 5
MINIMO_DE_PALAVRAS_INVALIDA = 3

SCHEMA_DA_RESPOSTA = {
    "type": "object",
    "properties": {
        "opiniao": {"type": "string", "enum": list(OPINIOES)},
        "risco": {"type": "string", "enum": list(RISCOS)},
        "justificativa": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"evidencia_id": {"type": "string"}, "leitura": {"type": "string"}},
                "required": ["evidencia_id", "leitura"],
            },
        },
    },
    "required": ["opiniao", "risco", "justificativa"],
}

SISTEMA = (
    "Você descreve, em português do Brasil, o que os números de um ativo da B3 indicam para um "
    "horizonte de tempo. Você NÃO é consultor e NÃO recomenda investimento.\n"
    "Regras obrigatórias:\n"
    "1. Use somente as evidências recebidas. Não use conhecimento próprio, notícias nem preços de memória.\n"
    "2. Escolha 'opiniao' somente entre as 'permitidas'. Na dúvida, prefira SINAL_NEUTRO ou SEM_BASE.\n"
    "3. Copie 'risco' exatamente como 'risco_calculado'.\n"
    "4. Use de 2 a 5 itens em 'justificativa', os que mais sustentam a 'opiniao'. Cada item cita um "
    "'evidencia_id' recebido e explica, em UMA frase de até 20 palavras, o que ele indica. Descreva o "
    "dado; não aconselhe nem diga se algo é bom para investir. Não invente números: use só os que "
    "aparecem nas evidências.\n"
    "5. Nunca prometa resultado. Palavras como 'garantido', 'certeza' e 'sem risco' são proibidas."
)


def montar_pedido(simbolo: str, dossie: DossieDeHorizonte) -> str:
    """Mensagem do usuario: so dados do dossie, em JSON fechado."""
    # Prompt curto: direcionais primeiro (quanto menor o pedido, mais rapido e menos divagacao).
    ordenadas = sorted(dossie.evidencias, key=lambda e: (e.direcao == 0, e.id))
    corpo = {
        "ativo": simbolo,
        "horizonte": NOME_DO_HORIZONTE[dossie.pregoes],
        "permitidas": list(dossie.permitidas),
        "risco_calculado": dossie.risco,
        "evidencias": [
            {"evidencia_id": e.id, "o_que_e": e.rotulo, "valor": e.valor,
             "leitura_numerica": {1: "favorável", -1: "desfavorável", 0: "informativa"}[e.direcao]}
            for e in ordenadas[:MAXIMO_DE_EVIDENCIAS_NO_PEDIDO]
        ],
    }
    return json.dumps(corpo, ensure_ascii=False)


_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_ID_TECNICO = re.compile(r"[a-z]+_[a-z0-9_]+")


def _numeros(texto: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMERO.findall(texto)}


def validar(resposta: object, dossie: DossieDeHorizonte) -> tuple[dict | None, list[str]]:
    """(resposta normalizada, erros). Erros vazios = valida."""
    erros: list[str] = []
    if not isinstance(resposta, dict):
        return None, ["resposta não é um objeto JSON"]
    opiniao, risco = resposta.get("opiniao"), resposta.get("risco")
    # "O que invalida" nao vem do modelo: sai das evidencias contrarias (condicoes_contrarias).
    # Se um modelo mandar o campo mesmo assim, ele e ignorado, mas tem de ser uma lista de textos.
    justificativa, invalida = resposta.get("justificativa"), resposta.get("o_que_invalida") or []

    if opiniao not in OPINIOES:
        erros.append(f"opiniao inválida: {opiniao!r}")
    elif opiniao not in dossie.permitidas:
        erros.append(f"opiniao {opiniao} fora das permitidas {list(dossie.permitidas)}")
    if risco not in RISCOS:
        erros.append(f"risco inválido: {risco!r}")
    elif risco != dossie.risco:
        erros.append(f"risco {risco} difere do calculado {dossie.risco}")
    if not isinstance(justificativa, list) or not all(isinstance(j, dict) for j in justificativa):
        erros.append("justificativa deve ser uma lista de objetos")
        justificativa = []
    if not isinstance(invalida, list) or not all(isinstance(i, str) for i in invalida):
        erros.append("o_que_invalida deve ser uma lista de textos")
        invalida = []
    if erros:
        return None, erros

    por_id: dict[str, Evidencia] = {e.id: e for e in dossie.evidencias}
    permitidos = {n for e in dossie.evidencias for n in _numeros(f"{e.valor} {e.rotulo}")}
    if opiniao != SEM_BASE and not justificativa:
        erros.append("opinião sem justificativa")
    citadas: list[Evidencia] = []
    for item in justificativa:
        ev = por_id.get(str(item.get("evidencia_id")))
        leitura = str(item.get("leitura") or "").strip()
        if ev is None:
            erros.append(f"evidência inexistente: {item.get('evidencia_id')!r}")
            continue
        citadas.append(ev)
        if not leitura or len(leitura) > LIMITE_LEITURA:
            erros.append(f"leitura vazia ou longa demais em {ev.id}")
        sobra = _numeros(leitura) - permitidos
        if sobra:
            erros.append(f"número fora do dossiê em {ev.id}: {sorted(sobra)}")
    if opiniao == POSITIVO and not any(e.direcao > 0 for e in citadas):
        erros.append("SINAL_POSITIVO sem citar evidência favorável")
    if opiniao == NEGATIVO and not any(e.direcao < 0 for e in citadas):
        erros.append("SINAL_NEGATIVO sem citar evidência desfavorável")
    textos = [str(j.get("leitura", "")) for j in justificativa] + invalida
    juntos = " ".join(textos).lower()
    achadas = [p for p in PALAVRAS_PROIBIDAS if p in juntos]
    if achadas:
        erros.append(f"vocabulário proibido: {achadas}")
    if len(justificativa) > MAXIMO_DE_JUSTIFICATIVAS:
        erros.append(f"justificativa: no máximo {MAXIMO_DE_JUSTIFICATIVAS} itens")
    # "O que invalida" e uma condicao futura, nao a repeticao de uma evidencia ou de um id.
    nomes = [t.lower() for e in dossie.evidencias for t in (e.rotulo, e.id)]
    if any(n in i.lower() for i in invalida for n in nomes) or any(_ID_TECNICO.search(i) for i in invalida):
        erros.append("o_que_invalida repete uma evidência em vez de dar uma condição")
    if len(invalida) > 3 or any(len(i) > LIMITE_INVALIDA for i in invalida):
        erros.append("o_que_invalida: máximo 3 itens curtos")
    if any(len(i.split()) < MINIMO_DE_PALAVRAS_INVALIDA for i in invalida):
        erros.append("o_que_invalida deve ter frases, não ids")
    if erros:
        return None, erros
    return {
        "opiniao": opiniao,
        "risco": risco,
        "justificativa": [{"evidencia_id": str(j["evidencia_id"]), "leitura": str(j["leitura"]).strip()}
                          for j in justificativa],
        "o_que_invalida": condicoes_contrarias(dossie, str(opiniao)),
    }, []


def condicoes_contrarias(dossie: DossieDeHorizonte, opiniao: str) -> list[str]:
    """"O que invalida" = as evidencias que apontam no sentido contrario da opiniao (ate 3), em texto."""
    sentido = {POSITIVO: 1, NEGATIVO: -1}.get(opiniao)
    if sentido is None:
        return []
    contra = [e for e in dossie.evidencias if e.direcao == -sentido]
    return [f"Há evidência em sentido contrário: {e.rotulo.lower()} ({e.valor})." for e in contra[:3]]


def resposta_de_regra(dossie: DossieDeHorizonte) -> dict:
    """Sem modelo (ou com resposta rejeitada): opiniao so pelas regras, texto montado dos numeros."""
    opiniao = dossie.permitidas[0]  # a ordem de `permitidas` ja vai da mais forte para a mais cautelosa
    sentido = {POSITIVO: 1, NEGATIVO: -1}.get(opiniao)
    direcionais = [e for e in dossie.evidencias if e.direcao != 0]
    if sentido is not None:
        # A justificativa lista o que SUSTENTA a opiniao; o que a contraria vira "o que invalida".
        a_favor = [e for e in direcionais if e.direcao == sentido]
    else:
        a_favor = direcionais
    if not a_favor:
        a_favor = dossie.evidencias[:2]
    justificativa = [{"evidencia_id": e.id, "leitura": f"{e.rotulo}: {e.valor}."}
                     for e in a_favor[:MAXIMO_DE_JUSTIFICATIVAS]]
    return {"opiniao": opiniao, "risco": dossie.risco, "justificativa": justificativa,
            "o_que_invalida": condicoes_contrarias(dossie, opiniao)}


class ProvedorLLM(Protocol):
    nome: str

    def gerar(self, sistema: str, usuario: str, schema: dict) -> str: ...


class ErroDoProvedor(RuntimeError):
    pass


class OllamaProvedor:
    """Ollama via /api/chat com saida estruturada (`format` = JSON Schema) e temperatura 0."""

    def __init__(self, url: str, modelo: str, timeout_s: int = 180, semente: int = 7, num_ctx: int = 2048,
                 max_tokens: int = 700):
        self._url = url.rstrip("/")
        self.nome = modelo
        self._timeout = timeout_s
        self._opcoes = {"temperature": 0, "seed": semente, "num_ctx": num_ctx, "num_predict": max_tokens}

    def gerar(self, sistema: str, usuario: str, schema: dict) -> str:
        corpo = json.dumps({
            "model": self.nome,
            "stream": False,
            "format": schema,
            "options": self._opcoes,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        }).encode("utf-8")
        pedido = urllib.request.Request(f"{self._url}/api/chat", data=corpo,
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=self._timeout) as resposta:  # noqa: S310
                dados = json.loads(resposta.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as erro:
            raise ErroDoProvedor(f"Ollama indisponível em {self._url}: {erro}") from erro
        return str((dados.get("message") or {}).get("content") or "")
