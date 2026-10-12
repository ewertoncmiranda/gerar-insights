"""LAC-INS-8/9: backtest por ranking ligado na etapa semanal (pre-registro, tentativas, falha isolada)."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from app.validacao import backtest_ranking as br


def test_toda_versao_tem_hipotese_pre_registrada():
    assert set(br.HIPOTESES) == set(br.VERSOES)
    assert all(len(h.strip()) >= 15 and "63 pregoes" in h for h in br.HIPOTESES.values())


def test_reexecutar_a_mesma_hipotese_nao_e_tentativa_nova():
    assert br.numero_da_tentativa([], "h1") == 1
    assert br.numero_da_tentativa(["h1", "h1", "h1"], "h1") == 1   # rodou toda sexta: continua 1
    assert br.numero_da_tentativa(["h1", "h1"], "h2") == 2         # hipotese nova: 2
    assert br.numero_da_tentativa(["h1", "h2", "h1"], "h2") == 2
    assert br.numero_da_tentativa(["  h1 ", None, ""], "h1") == 1  # espacos e vazios nao contam


def test_executar_todas_monta_amostras_uma_vez_e_isola_a_falha(monkeypatch):
    chamadas = {"montar": 0, "executar": []}

    def montar(db, inicio, corte):
        chamadas["montar"] += 1
        return (["amostra"], ["obs"], 1)

    @contextmanager
    def sessao():
        yield object()

    monkeypatch.setattr(br, "montar_amostras", montar)
    bt = br.BacktestRanking(sessao, logging.getLogger("teste"), repositorio=object())

    def executar(versao, hipotese, inicio, preparadas=None):
        chamadas["executar"].append((versao, hipotese, preparadas[0]))
        if versao == "VALOR_MOMENTO":
            raise RuntimeError("fatores ausentes")
        return 100 + len(chamadas["executar"])

    monkeypatch.setattr(bt, "executar", executar)
    saida = bt.executar_todas(versoes=("VALOR", "VALOR_MOMENTO", "GRAHAM_V1"))
    assert chamadas["montar"] == 1
    assert [v for v, _, _ in chamadas["executar"]] == ["VALOR", "VALOR_MOMENTO", "GRAHAM_V1"]
    assert all(h == br.HIPOTESES[v] and a == ["amostra"] for v, h, a in chamadas["executar"])
    assert saida == {"VALOR": 101, "VALOR_MOMENTO": None, "GRAHAM_V1": 103}
