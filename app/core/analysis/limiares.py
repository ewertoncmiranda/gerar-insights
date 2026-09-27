"""Limiares da regra oficial (v1), num lugar so e versionados (TASK-22, TASK-41).

Mudar qualquer valor aqui muda a recomendacao para a mesma entrada: exige
incrementar VERSAO_REGRA (versao_regra.py) e registrar o motivo em DEC-.
A calibracao (app/validacao/calibracao.py) testa combinacoes destes campos
usando SO o periodo de calibracao do backtest.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Limiares:
    # Graham: V = LPA x (multiplo_base + 2g) x 4,4 / Y. 8,5 e o P/L que Graham
    # dava a empresa sem crescimento nos EUA dos anos 1960 (ISS-F3): parametro,
    # nao constante.
    multiplo_base: float = 8.5

    # Compra forte: margem no cenario conservador e earnings yield minimos, e
    # preco ate o Graham Number quando ha VPA (ISS-F2).
    margem_compra_forte: float = 20.0
    ey_compra_forte: float = 12.0
    # Compra moderada: margem no cenario base e earnings yield minimos.
    margem_compra_moderada: float = 20.0
    ey_compra_moderada: float = 8.0
    # Faixa neutra (ISS-F3): entre margem_venda e 0 e MANTER; so abaixo e venda.
    # -100 na DEC-07 (modo G_REAL); -150 na DEC-08, com o modo G_NOMINAL.
    margem_venda: float = -150.0
    # Alerta de risco: perto da maxima de 52 semanas com pouca margem.
    posicao_alerta: float = 90.0
    margem_alerta: float = 10.0

    # Como juros e crescimento se combinam no Graham (TASK-54, DEC-08):
    #   G_REAL    Y = Selic (nominal), g real (0/3/5) - a versao 2026.09.27-2;
    #             dependia do regime de juros (DEC-07);
    #   G_NOMINAL Y = Selic, g = real + IPCA 12m (como a v2);
    #   Y_REAL    Y = Selic - IPCA 12m (piso de 2%), g real.
    # Adotado G_NOMINAL (DEC-08): fracao de vendas 20% -> 32% da calibracao
    # para o teste, contra 49% -> 70% no G_REAL.
    modo_juros: str = "G_NOMINAL"

    # LPA normalizado (ISS-F2): media dos ultimos anos entregues a CVM.
    anos_lpa_min: int = 3
    anos_lpa_max: int = 5

    def como_dict(self) -> dict:
        return dict(self.__dict__)


LIMIARES_ATUAIS = Limiares()
