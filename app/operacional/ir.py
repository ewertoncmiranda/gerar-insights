"""IR estimado do paper trading (OPR-INS-5, DEC-OPR-1). Puro, exceto `carregar_regras`.

Estimativa para comparar a carteira simulada com o CDI liquido de IR; nao e calculo oficial nem
orientacao tributaria. As regras vem de `OPERACIONAL_REGRAS_IR` (arquivo versionado por vigencia,
`ir/2026.json`), nunca fixas no codigo, e nada consulta a Receita.

Apuracao mensal (operacao comum em bolsa, por mes de `data_saida`):
- lucro do mes = soma de `resultado_pos_custos` das operacoes fechadas no mes;
- isencao: se a classe tem isencao (acao) e as vendas dessa classe no mes somam ate o limite, o
  lucro dela e isento; classes sem isencao (unit/ETF/FII, BDR) sempre tributam;
- prejuizo acumulado compensa lucro tributavel futuro (o de mes isento tambem, se a regra disser);
- devido = aliquota x base - IRRF (0,005% das vendas) do mes; nunca negativo;
- DARF abaixo do minimo nao e pago: acumula para o mes seguinte;
- entrada e saida no mesmo pregao seria day trade: a regra marca violacao (nao deveria ocorrer,
  porque a saida executa sempre na abertura de um pregao posterior).
O imposto do mes e rateado entre as operacoes com lucro do mes, na proporcao do lucro.
Recalcular tudo a partir das operacoes fechadas da o mesmo resultado: idempotente.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
REGRAS_PADRAO = "ir/2026.json"
D0 = Decimal(0)
CENTAVO = Decimal("0.01")

DAY_TRADE = "DAY_TRADE"
SEM_CLASSE = "SEM_CLASSE"


@dataclass(frozen=True)
class OperacaoFechada:
    id: int
    simbolo: str
    data_entrada: date
    data_saida: date
    valor_venda: Decimal           # preco_saida x quantidade
    resultado_pos_custos: Decimal


@dataclass
class ApuracaoMes:
    mes: str                                   # "AAAA-MM"
    vendas_por_classe: dict[str, Decimal] = field(default_factory=dict)
    lucro_isento: Decimal = D0
    lucro_tributavel: Decimal = D0             # antes da compensacao (pode ser negativo)
    prejuizo_compensado: Decimal = D0
    base: Decimal = D0
    irrf: Decimal = D0
    imposto_do_mes: Decimal = D0               # devido so deste mes (sem o resto de meses anteriores)
    a_pagar: Decimal = D0                      # imposto do mes + resto abaixo do DARF minimo
    pago: Decimal = D0                         # DARF do mes (0 se abaixo do minimo: vai para o seguinte)
    resto_para_o_seguinte: Decimal = D0
    prejuizo_acumulado: Decimal = D0           # ao fim do mes, para compensar adiante
    rateio: dict[int, Decimal] = field(default_factory=dict)  # operacao_id -> imposto rateado
    violacoes: list[dict] = field(default_factory=list)

    def como_json(self) -> dict:
        return {"mes": self.mes, "vendas_por_classe": {k: str(v) for k, v in self.vendas_por_classe.items()},
                "lucro_isento": str(self.lucro_isento), "lucro_tributavel": str(self.lucro_tributavel),
                "prejuizo_compensado": str(self.prejuizo_compensado), "base": str(self.base),
                "irrf": str(self.irrf), "imposto_do_mes": str(self.imposto_do_mes), "a_pagar": str(self.a_pagar),
                "pago": str(self.pago), "resto_para_o_seguinte": str(self.resto_para_o_seguinte),
                "prejuizo_acumulado": str(self.prejuizo_acumulado), "violacoes": self.violacoes}


@dataclass(frozen=True)
class RegrasIR:
    versao: str
    vigencias: tuple[dict, ...]

    def vigente(self, dia: date) -> dict:
        validas = [v for v in self.vigencias if date.fromisoformat(v["vigente_desde"]) <= dia]
        if not validas:
            raise ValueError(f"{self.versao}: nenhuma regra fiscal vigente em {dia}")
        return max(validas, key=lambda v: v["vigente_desde"])

    def classe(self, simbolo: str, dia: date) -> tuple[str, bool]:
        """(classe, tem isencao) pelo sufixo numerico do codigo de negociacao."""
        sufixo = simbolo.rstrip("F")[4:]
        for nome, c in self.vigente(dia)["classes"].items():
            if sufixo in c["sufixos"]:
                return nome, bool(c.get("isencao"))
        return SEM_CLASSE, False  # desconhecido: tributa (conservador)


def carregar_regras(caminho: str | None = None) -> RegrasIR:
    """`OPERACIONAL_REGRAS_IR` ou `regra_operacional.regras_ir_versao`, relativo a raiz do repo."""
    arquivo = Path(caminho or os.getenv("OPERACIONAL_REGRAS_IR", REGRAS_PADRAO))
    if not arquivo.is_absolute():
        arquivo = RAIZ / arquivo
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    return RegrasIR(dados["versao"], tuple(dados["vigencias"]))


def _mes(dia: date) -> str:
    return f"{dia.year:04d}-{dia.month:02d}"


def _c(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO)


def apurar(operacoes: list[OperacaoFechada], regras: RegrasIR) -> list[ApuracaoMes]:
    """Apuracao de cada mes com venda, em ordem, carregando prejuizo e resto de DARF."""
    por_mes: dict[str, list[OperacaoFechada]] = defaultdict(list)
    for op in operacoes:
        por_mes[_mes(op.data_saida)].append(op)
    prejuizo, resto = D0, D0
    saida: list[ApuracaoMes] = []
    for mes in sorted(por_mes):
        ops = por_mes[mes]
        regra = regras.vigente(max(op.data_saida for op in ops))
        comum = regra["operacao_comum"]
        a = ApuracaoMes(mes)

        lucro_classe: dict[str, Decimal] = defaultdict(lambda: D0)
        isenta: dict[str, bool] = {}
        for op in ops:
            if op.data_entrada == op.data_saida:
                a.violacoes.append({"codigo": DAY_TRADE, "operacao_id": op.id, "simbolo": op.simbolo,
                                    "detalhe": "entrada e saída no mesmo pregão (day trade não previsto)"})
            classe, tem_isencao = regras.classe(op.simbolo, op.data_saida)
            a.vendas_por_classe[classe] = a.vendas_por_classe.get(classe, D0) + op.valor_venda
            lucro_classe[classe] += op.resultado_pos_custos
            isenta[classe] = tem_isencao

        limite = Decimal(str(comum["isencao_vendas_mes"]))
        for classe, lucro in lucro_classe.items():
            if isenta[classe] and a.vendas_por_classe[classe] <= limite:
                if lucro >= 0:
                    a.lucro_isento += lucro
                    continue
                if not comum.get("prejuizo_em_mes_isento_compensa", True):
                    continue  # prejuizo de mes isento descartado
            a.lucro_tributavel += lucro

        if a.lucro_tributavel > 0:
            a.prejuizo_compensado = min(prejuizo, a.lucro_tributavel)
            a.base = a.lucro_tributavel - a.prejuizo_compensado
            prejuizo -= a.prejuizo_compensado
        else:
            prejuizo += -a.lucro_tributavel
        a.prejuizo_acumulado = _c(prejuizo)

        vendas_tributaveis = sum(v for c, v in a.vendas_por_classe.items()
                                 if not (isenta[c] and v <= limite))
        a.irrf = _c(vendas_tributaveis * Decimal(str(comum["irrf_sobre_vendas"])))
        a.imposto_do_mes = _c(max(D0, a.base * Decimal(str(comum["aliquota"])) - a.irrf))
        a.a_pagar = a.imposto_do_mes + resto
        if a.a_pagar >= Decimal(str(comum["darf_minimo"])):
            a.pago, resto = a.a_pagar, D0
        else:
            a.pago, resto = D0, a.a_pagar
        a.resto_para_o_seguinte = resto

        lucros = {op.id: op.resultado_pos_custos for op in ops if op.resultado_pos_custos > 0}
        total = sum(lucros.values(), D0)
        a.rateio = {i: (_c(a.imposto_do_mes * v / total) if total else D0) for i, v in lucros.items()}
        if a.rateio:  # o centavo de arredondamento vai para a maior operacao
            maior = max(lucros, key=lucros.get)
            a.rateio[maior] += a.imposto_do_mes - sum(a.rateio.values(), D0)
        for op in ops:
            a.rateio.setdefault(op.id, D0)
        saida.append(a)
    return saida


def provisao_em(apuracoes: list[ApuracaoMes], dia: date) -> tuple[Decimal, Decimal]:
    """(provisao, DARF a debitar) no pregao `dia`.

    provisao = o que o mes corrente ja deve (mais o resto de meses anteriores ainda nao pago);
    DARF = o `pago` do mes anterior, debitado do caixa no primeiro pregao do mes seguinte (quem
    chama decide se `dia` e esse primeiro pregao).
    """
    mes = _mes(dia)
    mes_anterior = _mes(date(dia.year - 1, 12, 1) if dia.month == 1 else date(dia.year, dia.month - 1, 1))
    anteriores = [a for a in apuracoes if a.mes < mes]
    atual = next((a for a in apuracoes if a.mes == mes), None)
    resto = anteriores[-1].resto_para_o_seguinte if anteriores else D0
    provisao = atual.a_pagar if atual else resto
    darf_anterior = next((a.pago for a in anteriores if a.mes == mes_anterior), D0)
    return provisao, darf_anterior
