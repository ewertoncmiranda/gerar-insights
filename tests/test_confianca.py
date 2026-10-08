from app.validacao.confianca import AmostraConfianca, curva_por_faixa


def test_curva_por_faixa_calcula_acerto_direcional():
    curva = curva_por_faixa(
        [
            AmostraConfianca(10, True),
            AmostraConfianca(15, False),
            AmostraConfianca(55, None),
            AmostraConfianca(82, True),
            AmostraConfianca(99, True),
            AmostraConfianca(None, True),
        ]
    )

    baixa = curva[0]
    media = next(f for f in curva if f.faixa == "40-59")
    alta = next(f for f in curva if f.faixa == "80-99")

    assert baixa.total == 2
    assert baixa.direcionais == 2
    assert baixa.acertos == 1
    assert baixa.taxa_acerto == 0.5
    assert media.total == 1
    assert media.direcionais == 0
    assert media.taxa_acerto is None
    assert alta.total == 2
    assert alta.taxa_acerto == 1.0


def test_curva_por_faixa_aceita_tuplas_e_limita_score():
    curva = curva_por_faixa([(-5, True), (100, False), (130, True)], tamanho_faixa=50)

    assert curva[0].faixa == "0-49"
    assert curva[0].total == 1
    assert curva[2].faixa == "100-100"
    assert curva[2].total == 2
    assert curva[2].taxa_acerto == 0.5
