"""Metodo de avaliacao por ranking entre acoes (LAC-INS-8) e regra de promocao
(LAC-INS-9). Puro.

Em vez de perguntar "quando a regra disse COMPRA, acertou?" (classes, com
pouco poder estatistico), pergunta "as acoes que a regra poe no topo rendem
mais que as do fundo?": todo mes, ordena o universo pelo score da versao e
mede a correlacao de Spearman entre score e retorno seguinte (o IC de
ranking) e o retorno de cada quintil.

Janelas sucessivas: treino expandindo desde 2011, teste de 12 meses, andando
ano a ano. Cada ano so e julgado por uma regra que nao o viu.

Muitas tentativas acham sorte: a melhor de N precisa passar num intervalo
mais largo (Bonferroni: nivel 5% / N).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date

MINIMO_ATIVOS_MES = 20
QUINTIS = 5
REAMOSTRAS = 2000
SEMENTE = 20260930
PREGOES_POR_MES = 21
CUSTO_IDA_E_VOLTA = 0.0010


# --- estatisticas de um mes ----------------------------------------------


def postos(valores: list[float]) -> list[float]:
    """Posto medio (1..n), empates dividindo a posicao."""
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    saida = [0.0] * len(valores)
    i = 0
    while i < len(ordem):
        j = i
        while j + 1 < len(ordem) and valores[ordem[j + 1]] == valores[ordem[i]]:
            j += 1
        for k in range(i, j + 1):
            saida[ordem[k]] = (i + j) / 2 + 1
        i = j + 1
    return saida


def spearman(scores: list[float], retornos: list[float]) -> float | None:
    """Correlacao de Pearson entre os postos. None com poucos papeis ou sem variacao."""
    if len(scores) != len(retornos) or len(scores) < MINIMO_ATIVOS_MES:
        return None
    ps, pr = postos(scores), postos(retornos)
    ms, mr = sum(ps) / len(ps), sum(pr) / len(pr)
    cov = sum((a - ms) * (b - mr) for a, b in zip(ps, pr))
    vs = sum((a - ms) ** 2 for a in ps)
    vr = sum((b - mr) ** 2 for b in pr)
    if vs == 0 or vr == 0:
        return None
    return cov / math.sqrt(vs * vr)


def quintis(scores: list[float], retornos: list[float]) -> list[tuple[int, float, int]] | None:
    """(quintil 1..5, retorno medio, papeis): quintil 1 = menor score."""
    if len(scores) < MINIMO_ATIVOS_MES:
        return None
    ordem = sorted(range(len(scores)), key=lambda i: (scores[i], i))
    saida = []
    for q in range(QUINTIS):
        fatia = ordem[q * len(ordem) // QUINTIS : (q + 1) * len(ordem) // QUINTIS]
        if not fatia:
            return None
        saida.append((q + 1, sum(retornos[i] for i in fatia) / len(fatia), len(fatia)))
    return saida


@dataclass(frozen=True)
class MesRanking:
    data_referencia: date
    horizonte: int
    ic: float | None
    quintis: list[tuple[int, float, int]] | None
    n_ativos: int

    @property
    def diferenca_extremos(self) -> float | None:
        """Quintil 5 menos o 1, depois do custo de montar as duas pontas."""
        if not self.quintis:
            return None
        return self.quintis[-1][1] - self.quintis[0][1] - 2 * CUSTO_IDA_E_VOLTA


def medir_mes(data_ref: date, horizonte: int, score: dict[str, float], retorno: dict[str, float]) -> MesRanking:
    comuns = sorted(s for s in score if s in retorno)
    sc = [score[s] for s in comuns]
    rt = [retorno[s] for s in comuns]
    return MesRanking(data_ref, horizonte, spearman(sc, rt), quintis(sc, rt), len(comuns))


# --- janelas sucessivas ----------------------------------------------------


@dataclass(frozen=True)
class Janela:
    nome: str
    treino_inicio: date
    treino_fim: date
    teste_inicio: date
    teste_fim: date

    def contem_teste(self, dia: date) -> bool:
        return self.teste_inicio <= dia <= self.teste_fim


def janelas_sucessivas(inicio_treino: int = 2011, primeiro_teste: int = 2016, ultimo_teste: int = 2026) -> list[Janela]:
    """Treino de `inicio_treino` ate o fim do ano anterior ao teste; teste de 12 meses."""
    return [
        Janela(f"T{ano}", date(inicio_treino, 1, 1), date(ano - 1, 12, 31), date(ano, 1, 1), date(ano, 12, 31))
        for ano in range(primeiro_teste, ultimo_teste + 1)
    ]


# --- intervalo e promocao ----------------------------------------------------


def nivel_corrigido(numero_tentativa: int | None) -> float:
    """Nivel de significancia bicaudal para a melhor de N tentativas (Bonferroni)."""
    return 0.05 / max(1, numero_tentativa or 1)


def intervalo_da_media(serie: list[tuple[date, float]], horizonte: int, nivel: float = 0.05) -> tuple[float, float] | None:
    """IC da media de uma serie mensal por bootstrap em blocos de meses
    consecutivos (meses de janelas sobrepostas andam juntos)."""
    valores = [v for _, v in sorted(serie)]
    if len(valores) < 12:
        return None
    bloco = max(1, min(len(valores), math.ceil(horizonte / PREGOES_POR_MES)))
    blocos = math.ceil(len(valores) / bloco)
    gerador = random.Random(SEMENTE)
    medias = []
    for _ in range(REAMOSTRAS):
        amostra: list[float] = []
        for _ in range(blocos):
            inicio = gerador.randrange(len(valores) - bloco + 1)
            amostra.extend(valores[inicio : inicio + bloco])
        medias.append(sum(amostra) / len(amostra))
    medias.sort()
    baixo = medias[max(0, int(nivel / 2 * REAMOSTRAS))]
    alto = medias[min(REAMOSTRAS - 1, int((1 - nivel / 2) * REAMOSTRAS) - 1)]
    return baixo, alto


@dataclass(frozen=True)
class Decisao:
    promover: bool
    motivos: list[str]
    ic_medio: float | None
    ic_intervalo: tuple[float, float] | None
    diferenca_extremos_media: float | None


def decidir_promocao(
    meses_teste: list[MesRanking],
    horizonte: int,
    numero_tentativa: int | None,
    alfa: float | None,
    diario_contradiz: bool | None,
) -> Decisao:
    """Criterios da LAC-INS-9, so com os meses de TESTE das janelas sucessivas.

    alfa: intercepto da regressao contra os fatores de referencia (None = nao medido).
    diario_contradiz: None enquanto o diario ao vivo nao tem horizonte vencido."""
    ics = [(m.data_referencia, m.ic) for m in meses_teste if m.ic is not None]
    difs = [m.diferenca_extremos for m in meses_teste if m.diferenca_extremos is not None]
    ic_medio = sum(v for _, v in ics) / len(ics) if ics else None
    intervalo = intervalo_da_media(ics, horizonte, nivel_corrigido(numero_tentativa))
    dif_media = sum(difs) / len(difs) if difs else None

    motivos = []
    if intervalo is None:
        motivos.append("meses de teste insuficientes para o intervalo do IC de ranking")
    elif intervalo[0] <= 0:
        motivos.append(f"intervalo do IC de ranking toca o zero ({intervalo[0]:.4f} a {intervalo[1]:.4f})")
    if dif_media is None or dif_media <= 0:
        motivos.append("quintil 5 menos quintil 1 nao e positivo depois de custos")
    if alfa is None:
        motivos.append("alfa contra os fatores de referencia nao medido")
    elif alfa < 0:
        motivos.append(f"alfa negativo contra os fatores de referencia ({alfa:.4f})")
    if diario_contradiz:
        motivos.append("o diario ao vivo contradiz o backtest")
    return Decisao(not motivos, motivos, ic_medio, intervalo, dif_media)
