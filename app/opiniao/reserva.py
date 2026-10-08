"""Reserva por regra: a opiniao que existe sem o servico de IA, montada so dos numeros do dossie.

Usada pelo `--sem-llm` e quando o servico de IA nao responde. E a mesma regra do servico
(insider-ia-b3-ecossytem, app/regras.py): com ou sem servico, a linha REGRA de opiniao_ia sai
igual (aceite da TASK-IA-03). O prompt, o schema e o validador do modelo moram no servico.
"""

from __future__ import annotations

from app.opiniao.regras import NEGATIVO, POSITIVO, DossieDeHorizonte

MAXIMO_DE_JUSTIFICATIVAS = 5
MAXIMO_DE_CONDICOES = 3


def condicoes_contrarias(dossie: DossieDeHorizonte, opiniao: str) -> list[str]:
    """"O que invalida" = as evidencias que apontam no sentido contrario da opiniao (ate 3), em texto."""
    sentido = {POSITIVO: 1, NEGATIVO: -1}.get(opiniao)
    if sentido is None:
        return []
    contra = [e for e in dossie.evidencias if e.direcao == -sentido]
    return [f"Há evidência em sentido contrário: {e.rotulo.lower()} ({e.valor})."
            for e in contra[:MAXIMO_DE_CONDICOES]]


def resposta_de_regra(dossie: DossieDeHorizonte) -> dict:
    """{opiniao, risco, justificativa, o_que_invalida} pela regra; a ordem de `permitidas` vai da
    opiniao mais forte para a mais cautelosa, entao a primeira e a da regra."""
    opiniao = dossie.permitidas[0]
    sentido = {POSITIVO: 1, NEGATIVO: -1}.get(opiniao)
    direcionais = [e for e in dossie.evidencias if e.direcao != 0]
    # A justificativa lista o que SUSTENTA a opiniao; o que a contraria vira "o que invalida".
    a_favor = [e for e in direcionais if e.direcao == sentido] if sentido is not None else direcionais
    if not a_favor:
        a_favor = dossie.evidencias[:2]
    justificativa = [{"evidencia_id": e.id, "leitura": f"{e.rotulo}: {e.valor}."}
                     for e in a_favor[:MAXIMO_DE_JUSTIFICATIVAS]]
    return {"opiniao": opiniao, "risco": dossie.risco, "justificativa": justificativa,
            "o_que_invalida": condicoes_contrarias(dossie, opiniao)}
