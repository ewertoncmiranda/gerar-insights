import pytest

from app.core.analysis.limiares import LIMIARES_ATUAIS
from app.core.analysis.valuation import GrahamValuation, ValuationAnalyzer


def test_graham_nominal_exige_ipca():
    with pytest.raises(ValueError, match="precisa do IPCA"):
        GrahamValuation().calculate_scenarios(2.0, 10.0, 10.0, modo="G_NOMINAL")


def test_classificacoes_cobrem_todas_as_faixas():
    analyzer = ValuationAnalyzer()
    assert [analyzer.classify_price_earnings(valor) for valor in (None, 7.0, 15.0, 20.0, 21.0)] == [
        "NAO_DISPONIVEL",
        "BAIXO_COM_ATENCAO",
        "SAUDAVEL",
        "ESTICADO",
        "EXIGENTE",
    ]
    assert [analyzer.classify_earnings_yield(valor) for valor in (None, 12.0, 8.0, 6.0, 5.0)] == [
        "NAO_DISPONIVEL",
        "ATRATIVO",
        "RAZOAVEL",
        "BAIXO",
        "MUITO_BAIXO",
    ]


def test_limiares_sao_serializaveis_sem_expor_estado_mutavel():
    valores = LIMIARES_ATUAIS.como_dict()
    valores["multiplo_base"] = 99
    assert LIMIARES_ATUAIS.multiplo_base == 8.5
