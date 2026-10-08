"""Cliente HTTP do servico de IA (insider-ia-b3-ecossytem, CTR-IA-01) - TASK-IA-03.

O worker nao conhece prompt, schema, validador nem modelo: manda o dossie (evidencias, opinioes
permitidas e risco, calculados por regras.py) para `POST /opiniao` e grava o que voltar. O
servico ja devolve a reserva por regra quando o modelo falha ou e rejeitado; este cliente so
levanta `ErroDoServicoIA` quando o proprio servico nao responde (rede, 4xx/5xx, JSON invalido).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date

from app.opiniao.regras import DossieDeHorizonte


class ErroDoServicoIA(RuntimeError):
    pass


@dataclass(frozen=True)
class Identidade:
    """Quem vai responder: o modelo de chat e a versao do conjunto de skills (`skills@<hash>`)."""

    modelo: str
    skills_versao: str


def pedido_do_dossie(simbolo: str, data_pregao: date, dossie: DossieDeHorizonte,
                     dados_ausentes: list[str], versao_regra: str) -> dict:
    """Corpo de `POST /opiniao` (SPEC 5.1). `permitidas` ja vem da mais forte para a mais cautelosa."""
    return {
        "simbolo": simbolo,
        "data_pregao": data_pregao.isoformat(),
        "horizonte_pregoes": dossie.pregoes,
        "evidencias": [{"id": e.id, "rotulo": e.rotulo, "valor": e.valor, "direcao": e.direcao}
                       for e in dossie.evidencias],
        "permitidas": list(dossie.permitidas),
        "risco_calculado": dossie.risco,
        "motivo_sem_base": dossie.motivo_sem_base,
        "dados_ausentes": list(dados_ausentes),
        "versao_regra": versao_regra,
    }


class ServicoIA:
    def __init__(self, url: str, timeout_s: int = 300):
        self._url = url.rstrip("/")
        # O servico pode fazer duas chamadas ao modelo por pedido (segunda com os erros da primeira).
        self._timeout = timeout_s

    def identidade(self) -> Identidade:
        """`GET /saude`: modelo e versao das skills, para a chave de idempotencia antes de opinar."""
        dados = self._chamar("GET", "/saude", None, timeout=10)
        modelo, versao = dados.get("modelo"), dados.get("skills_versao")
        if not modelo or not versao:
            raise ErroDoServicoIA(f"/saude sem modelo ou skills_versao: {dados}")
        return Identidade(str(modelo), str(versao))

    def opinar(self, pedido: dict) -> dict:
        """`POST /opiniao`; devolve a resposta do contrato (origem MODELO ou REGRA)."""
        resposta = self._chamar("POST", "/opiniao", pedido, timeout=self._timeout)
        faltando = [c for c in ("opiniao", "risco", "justificativa", "o_que_invalida", "modelo",
                                "skills_versao", "origem") if c not in resposta]
        if faltando:
            raise ErroDoServicoIA(f"/opiniao sem os campos {faltando}")
        return resposta

    def _chamar(self, metodo: str, caminho: str, corpo: dict | None, timeout: int) -> dict:
        dados = None if corpo is None else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        pedido = urllib.request.Request(f"{self._url}{caminho}", data=dados, method=metodo,
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resposta:  # noqa: S310 (rede interna)
                return json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")[:300]
            raise ErroDoServicoIA(f"{metodo} {caminho} -> HTTP {erro.code}: {detalhe}") from erro
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as erro:
            raise ErroDoServicoIA(f"servico de IA indisponivel em {self._url}: {erro}") from erro
