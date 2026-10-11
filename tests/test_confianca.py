from datetime import date

from sqlalchemy import create_engine, text

from app.validacao.confianca import AmostraConfianca, curva_por_faixa, curva_real
from app.validacao.repositorio_diario import RepositorioDiario


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


def test_curva_real_explicita_ausencia_de_evidencia_direcional():
    curva = curva_real([AmostraConfianca(55, None)])

    assert curva.total == 1
    assert curva.direcionais == 0
    assert curva.tem_evidencia_real is False


def test_repositorio_extrai_amostras_reais_da_base_do_diario():
    engine = create_engine("sqlite:///:memory:")
    db = engine.connect()
    db.execute(
        text(
            "CREATE TABLE sinal_diario ("
            "id INTEGER PRIMARY KEY, simbolo TEXT, data_pregao DATE, "
            "versao_regra TEXT, confianca_score INTEGER)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE sinal_resultado ("
            "id INTEGER PRIMARY KEY, sinal_id INTEGER, horizonte INTEGER, acerto INTEGER)"
        )
    )
    db.execute(
        text(
            "INSERT INTO sinal_diario "
            "(id, simbolo, data_pregao, versao_regra, confianca_score) VALUES "
            "(1, 'PETR4', '2026-10-01', 'v1', 80), "
            "(2, 'VALE3', '2026-10-02', 'v1', 40), "
            "(3, 'ITUB4', '2026-10-03', 'v2', 70), "
            "(4, 'BBDC4', '2026-10-04', 'v1', NULL)"
        )
    )
    db.execute(
        text(
            "INSERT INTO sinal_resultado (sinal_id, horizonte, acerto) VALUES "
            "(1, 21, 1), (1, 63, 0), (2, 21, NULL), (3, 21, 1), (4, 21, 1)"
        )
    )

    amostras = RepositorioDiario().amostras_confianca(
        db,
        versao_regra="v1",
        horizonte=21,
        desde=date(2026, 10, 1),
        ate=date(2026, 10, 2),
    )

    assert amostras == [
        AmostraConfianca(80, True),
        AmostraConfianca(40, None),
    ]
