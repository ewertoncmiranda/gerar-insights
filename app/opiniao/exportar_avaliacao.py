"""Exporta o conjunto de avaliacao do servico de IA (insider-ia, TASK-IA-05).

    python -m app.opiniao.exportar_avaliacao --data 2026-10-06 --saida ../insider-ia-b3-ecossytem/avaliacao

Para cada ativo e horizonte do pregao grava, em JSONL:
  dossies/<data>.jsonl   a ENTRADA do CTR-IA-01 (evidencias, permitidas, risco_calculado, ...)
  esperado/<data>.jsonl  o que a reserva por regra responde para ela (opiniao, risco, justificativa, invalida)

As entradas saem das mesmas regras que o worker usa (montar_dossie); nada vem do modelo. O arquivo
e congelado: serve de regressao para o servico (a regra nao pode mudar sem mudar o esperado).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.opiniao.modelo_llm import resposta_de_regra
from app.opiniao.regras import HORIZONTES, montar_dossie
from app.opiniao.repositorio import RepositorioOpiniao


def entrada_do_servico(simbolo: str, data_pregao: date, horizonte: int, dossie, ausentes: list[str],
                       versao_regra: str) -> dict:
    d = dossie[horizonte]
    return {
        "simbolo": simbolo,
        "data_pregao": data_pregao.isoformat(),
        "horizonte_pregoes": horizonte,
        "evidencias": [{"id": e.id, "rotulo": e.rotulo, "valor": e.valor, "direcao": e.direcao}
                       for e in d.evidencias],
        "permitidas": list(d.permitidas),
        "risco_calculado": d.risco,
        "motivo_sem_base": d.motivo_sem_base,
        "dados_ausentes": ausentes,
        "versao_regra": versao_regra,
    }


def exportar(db, data_pregao: date, saida: Path) -> int:
    repo = RepositorioOpiniao()
    (saida / "dossies").mkdir(parents=True, exist_ok=True)
    (saida / "esperado").mkdir(parents=True, exist_ok=True)
    linhas_in: list[str] = []
    linhas_out: list[str] = []
    for simbolo in repo.simbolos_do_pregao(db, data_pregao):
        insight = repo.ultimo_insight(db, simbolo, data_pregao)
        if insight is None:
            continue
        dossie, ausentes = montar_dossie(insight["detalhes"], repo.fatores_recentes(db, simbolo),
                                         repo.fatos_relevantes_30d(db, simbolo, data_pregao), data_pregao)
        versao_regra = str(insight["detalhes"].get("versao_regra") or "")
        for h in HORIZONTES:
            entrada = entrada_do_servico(simbolo, data_pregao, h, dossie, ausentes, versao_regra)
            linhas_in.append(json.dumps(entrada, ensure_ascii=False, sort_keys=True))
            esperado = resposta_de_regra(dossie[h])
            esperado.update({"simbolo": simbolo, "horizonte_pregoes": h})
            linhas_out.append(json.dumps(esperado, ensure_ascii=False, sort_keys=True))
    (saida / "dossies" / f"{data_pregao}.jsonl").write_text("\n".join(linhas_in) + "\n", encoding="utf-8")
    (saida / "esperado" / f"{data_pregao}.jsonl").write_text("\n".join(linhas_out) + "\n", encoding="utf-8")
    return len(linhas_in)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta dossies e respostas esperadas (regra)")
    parser.add_argument("--data", type=date.fromisoformat, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    argumentos = parser.parse_args(argv)

    from app.config.database_config import ConfigDatabase

    with ConfigDatabase().session() as db:
        total = exportar(db, argumentos.data, argumentos.saida)
    print(f"{total} dossies exportados para {argumentos.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
