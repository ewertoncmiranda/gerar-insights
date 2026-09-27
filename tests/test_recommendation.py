"""Faixa neutra do VENDA_VALUATION (ISS-F3) e a segunda trava do COMPRA_FORTE
via Graham Number (ISS-F2). Sem teste ate aqui - a logica existia so em codigo."""

from app.core.analysis.limiares import LIMIARES_ATUAIS
from app.core.analysis.recommendation import RecommendationPolicy


def valuation(conservador, base, earnings_yield=10.0, preco_ate_graham_number=None):
    return {
        "cenarios_graham": {
            "conservador": {"margem_seguranca_percent": conservador},
            "base": {"margem_seguranca_percent": base},
        },
        "earnings_yield": earnings_yield,
        "preco_ate_graham_number": preco_ate_graham_number,
    }


def test_venda_valuation_so_abaixo_da_faixa_neutra():
    """ISS-F3: margem_venda = -15. Abaixo disso, e so entao, e VENDA_VALUATION."""
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=-20, base=-16), range_52w_position=50
    )
    assert recomendacao == "VENDA_VALUATION"


def test_margem_negativa_mas_dentro_da_faixa_neutra_e_manter():
    """Antes do ISS-F3, qualquer margem base negativa virava venda - agora
    so abaixo de -15% (a faixa entre -15 e 0 e MANTER)."""
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=-10, base=-5), range_52w_position=50
    )
    assert recomendacao == "MANTER"


def test_faixa_neutra_no_limite_exato_ainda_e_manter():
    limite = LIMIARES_ATUAIS.margem_venda
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=-20, base=limite), range_52w_position=50
    )
    assert recomendacao == "MANTER"


def test_compra_forte_quando_margem_alta_e_dentro_do_graham_number():
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=25, base=25, earnings_yield=15, preco_ate_graham_number=True),
        range_52w_position=50,
    )
    assert recomendacao == "COMPRA_FORTE"


def test_compra_forte_rebaixada_quando_preco_passa_do_graham_number():
    """ISS-F2: barato pelo lucro (Graham classico) mas caro pelo patrimonio
    (acima do Graham Number) rebaixa de COMPRA_FORTE pra COMPRA_MODERADA."""
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=25, base=25, earnings_yield=15, preco_ate_graham_number=False),
        range_52w_position=50,
    )
    assert recomendacao == "COMPRA_MODERADA"


def test_compra_forte_sem_dado_de_graham_number_nao_e_rebaixada():
    """Sem VPA disponivel, preco_ate_graham_number vem None - nao ha segunda
    trava pra aplicar, mas tambem nao deve travar a compra forte."""
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=25, base=25, earnings_yield=15, preco_ate_graham_number=None),
        range_52w_position=50,
    )
    assert recomendacao == "COMPRA_FORTE"


def test_compra_moderada_com_margem_base_alta_e_earnings_yield_moderado():
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=5, base=22, earnings_yield=9),
        range_52w_position=50,
    )
    assert recomendacao == "COMPRA_MODERADA"


def test_alerta_risco_perto_da_maxima_com_pouca_margem():
    policy = RecommendationPolicy()
    recomendacao = policy.define_recommendation(
        valuation(conservador=5, base=5, earnings_yield=7),
        range_52w_position=95,
    )
    assert recomendacao == "ALERTA_RISCO"
