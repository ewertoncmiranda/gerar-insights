import math

from app.core.analysis.limiares import LIMIARES_ATUAIS, Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.number_utils import percent
from app.core.analysis.number_utils import round_metric

# Rendimento de referencia da formula revisada de Graham (titulos AAA dos EUA
# em 1962). O preco justo e multiplicado por 4,4 / Y (DEC-02).
TAXA_REFERENCIA_GRAHAM = 4.4
# Piso de sanidade: com Y perto de zero o fator 4,4/Y explode.
TAXA_MINIMA = 2.0

# Modos de combinar juros e crescimento (limiares.modo_juros, TASK-54).
MODO_G_REAL = "G_REAL"
MODO_G_NOMINAL = "G_NOMINAL"
MODO_Y_REAL = "Y_REAL"
MODOS_JUROS = (MODO_G_REAL, MODO_G_NOMINAL, MODO_Y_REAL)


class GrahamValuation:
    """V = LPA x (multiplo_base + 2g) x 4,4 / Y.

    Y e a taxa livre de risco do dia (DEC-02: Selic meta vigente, SGS 432).
    Sem o fator, com a Selic brasileira na casa dos dois digitos, o valor justo
    sai varias vezes inflado e quase tudo parece barato (ISS-F1). O cenario
    sem o fator continua sendo calculado, so como referencia historica - nao
    entra na recomendacao.
    """

    SCENARIOS = {
        "conservador": 0,
        "base": 3,
        "otimista": 5,
    }

    def __init__(self, multiplo_base: float = LIMIARES_ATUAIS.multiplo_base):
        self.multiplo_base = multiplo_base

    def calculate_scenarios(
        self,
        earnings_per_share: float,
        price: float,
        taxa_juros: float = TAXA_REFERENCIA_GRAHAM,
        ipca: float | None = None,
        modo: str = MODO_G_REAL,
    ) -> dict:
        """modo G_NOMINAL soma o IPCA ao crescimento; Y_REAL desconta o IPCA
        da taxa. Nominal com nominal, ou real com real: o G_REAL mistura os
        dois e por isso a margem acompanhava a Selic (DEC-07)."""
        if modo != MODO_G_REAL and ipca is None:
            raise ValueError(f"modo {modo} precisa do IPCA 12m")
        taxa = taxa_juros - ipca if modo == MODO_Y_REAL else taxa_juros
        inflacao = ipca if modo == MODO_G_NOMINAL else 0.0
        fator = fator_de_juros(taxa)
        scenarios = {}
        for name, real in self.SCENARIOS.items():
            growth = real + inflacao
            implied_earnings_multiple = (self.multiplo_base + 2 * growth) * fator
            fair_price = earnings_per_share * implied_earnings_multiple
            scenarios[name] = {
                "crescimento_percent": round_metric(growth),
                "taxa_usada_percent": round_metric(max(taxa, TAXA_MINIMA)),
                "multiplo_lucro_implicito": round_metric(implied_earnings_multiple),
                "preco_justo": round_metric(fair_price),
                "margem_seguranca_percent": round_metric(percent(fair_price - price, fair_price)),
            }
        return scenarios


def fator_de_juros(taxa_juros: float) -> float:
    """4,4 / Y, com Y em % ao ano; Y = 4,4 devolve 1 (a formula original)."""
    return TAXA_REFERENCIA_GRAHAM / max(taxa_juros, TAXA_MINIMA)


def normalizar_lpa(
    lpa_atual: float | None, lpas_anuais: list[float] | None, limiares: Limiares = LIMIARES_ATUAIS
) -> tuple[float | None, str, float | None]:
    """LPA usado no valuation (ISS-F2): o MENOR entre o atual e a media dos
    ultimos 3 a 5 exercicios entregues a CVM (mais recente primeiro).

    Media porque ciclica no pico do lucro parece barata com o LPA do ano;
    minimo porque, com o lucro caindo, a media ainda carrega os anos bons.
    Sem 3 exercicios, fica o LPA atual - e a fonte diz isso.
    Devolve (lpa_usado, fonte, media)."""
    # LPA exatamente zero e conta nao resolvida no ETL (lucro do controlador
    # gravado como 0 em vez de ausente - TIMS3, LREN3, HAPV3, JBSS32), nao
    # empresa que lucrou zero: conta como dado ausente.
    anuais = [x for x in (lpas_anuais or []) if x is not None and x != 0][: limiares.anos_lpa_max]
    if len(anuais) < limiares.anos_lpa_min:
        return lpa_atual, "LPA_ATUAL (historico da CVM insuficiente)", None
    media = sum(anuais) / len(anuais)
    if lpa_atual is not None and lpa_atual < media:
        return lpa_atual, f"LPA_ATUAL (abaixo da media de {len(anuais)} anos)", media
    return media, f"MEDIA_{len(anuais)}_ANOS", media


def graham_number(lpa: float | None, vpa: float | None) -> float | None:
    """sqrt(22,5 x LPA x VPA): P/L 15 x P/VPA 1,5. Nao usa juros - e o teto
    classico de Graham para o investidor defensivo, segundo criterio de compra."""
    if not lpa or not vpa or lpa <= 0 or vpa <= 0:
        return None
    return math.sqrt(22.5 * lpa * vpa)


class ValuationAnalyzer:
    def __init__(self, graham: GrahamValuation | None = None, limiares: Limiares = LIMIARES_ATUAIS):
        self.limiares = limiares
        self.graham = graham or GrahamValuation(limiares.multiplo_base)

    def analyze(
        self,
        snapshot: MarketSnapshot,
        taxa_juros: float,
        fonte_taxa: str = "INFORMADA",
        lpas_anuais: list[float] | None = None,
        vpa: float | None = None,
        ipca_12m: float | None = None,
    ) -> dict:
        """taxa_juros: Y em % ao ano. Obrigatoria de proposito - cair para a
        formula sem juros quando a taxa falta misturaria duas regras sob a
        mesma versao. lpas_anuais (mais recente primeiro) e vpa vem da CVM,
        ja filtrados pela data de entrega."""
        lpa, fonte_lpa, media = normalizar_lpa(snapshot.earnings_per_share, lpas_anuais, self.limiares)
        modo = self.limiares.modo_juros
        # Modo que usa IPCA sem IPCA disponivel: invalido, nunca cai em outro modo.
        valido = (lpa is not None and lpa > 0 and bool(snapshot.price)
                  and (modo == MODO_G_REAL or ipca_12m is not None))
        earnings_yield = percent(lpa, snapshot.price) if valido else None
        scenarios = (
            self.graham.calculate_scenarios(lpa, snapshot.price, taxa_juros, ipca_12m, modo) if valido else None
        )
        referencia = (
            GrahamValuation(self.limiares.multiplo_base).calculate_scenarios(
                lpa, snapshot.price, TAXA_REFERENCIA_GRAHAM
            )
            if valido
            else None
        )
        numero = graham_number(lpa, vpa) if valido else None

        return {
            "valido": valido,
            "earnings_yield": earnings_yield,
            "earnings_yield_percent": round_metric(earnings_yield),
            "classificacao_pl": self.classify_price_earnings(snapshot.price_earnings),
            "classificacao_earnings_yield": self.classify_earnings_yield(earnings_yield),
            "cenarios_graham": scenarios,
            "cenario_base": scenarios["base"] if scenarios else None,
            "crescimento_base": self.graham.SCENARIOS["base"],
            "taxa_livre_risco_percent": round_metric(taxa_juros),
            "fonte_taxa_livre_risco": fonte_taxa,
            "fator_juros": round_metric(fator_de_juros(taxa_juros)),
            "modo_juros": modo,
            "ipca_12m_percent": round_metric(ipca_12m),
            # So referencia: a formula de 1962 sem o ajuste de juros.
            "cenarios_graham_sem_ajuste_juros": referencia,
            "lpa_atual": round_metric(snapshot.earnings_per_share),
            "lpa_usado": round_metric(lpa),
            "lpa_medio": round_metric(media),
            "fonte_lpa": fonte_lpa,
            "vpa": round_metric(vpa),
            "graham_number": round_metric(numero),
            "preco_ate_graham_number": None if numero is None else snapshot.price <= numero,
            "multiplo_base": self.limiares.multiplo_base,
        }

    def classify_price_earnings(self, price_earnings: float | None) -> str:
        if price_earnings is None or price_earnings <= 0:
            return "NAO_DISPONIVEL"
        if price_earnings < 8:
            return "BAIXO_COM_ATENCAO"
        if price_earnings <= 15:
            return "SAUDAVEL"
        if price_earnings <= 20:
            return "ESTICADO"
        return "EXIGENTE"

    def classify_earnings_yield(self, earnings_yield: float | None) -> str:
        if earnings_yield is None:
            return "NAO_DISPONIVEL"
        if earnings_yield >= 12:
            return "ATRATIVO"
        if earnings_yield >= 8:
            return "RAZOAVEL"
        if earnings_yield >= 6:
            return "BAIXO"
        return "MUITO_BAIXO"
