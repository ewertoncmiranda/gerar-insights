from app.operacional.opcoes import (
    CADEIA_OPCOES_NAO_VALIDADA,
    CADEIA_OPCOES_VALIDADA,
    avaliar_uso_decisorio,
)


def test_bloqueia_quando_saude_ausente():
    resultado = avaliar_uso_decisorio(None)

    assert resultado.permitido is False
    assert resultado.codigo == CADEIA_OPCOES_NAO_VALIDADA
    assert "saude_opcoes_ausente" in resultado.motivos


def test_bloqueia_base_contaminada_mesmo_com_contrato():
    resultado = avaliar_uso_decisorio(
        {
            "status": "BASE_OPCOES_CONTAMINADA",
            "registrosValidos": 0,
            "registrosLegadoNaoValidado": 321410,
            "percentualValido": "0.00",
        }
    )

    assert resultado.permitido is False
    assert resultado.codigo == CADEIA_OPCOES_NAO_VALIDADA
    assert "status=BASE_OPCOES_CONTAMINADA" in resultado.motivos
    assert "sem_registros_validos" in resultado.motivos
    assert "legado_nao_validado=321410" in resultado.motivos


def test_permite_somente_quando_cadeia_validada():
    resultado = avaliar_uso_decisorio(
        {
            "status": "OK",
            "registrosValidos": 120,
            "registrosLegadoNaoValidado": 0,
            "percentualValido": "98.50",
        }
    )

    assert resultado.permitido is True
    assert resultado.codigo == CADEIA_OPCOES_VALIDADA
    assert resultado.motivos == []


def test_aceita_chaves_snake_case_da_view():
    resultado = avaliar_uso_decisorio(
        {
            "registros_validos": 3,
            "registros_legado_nao_validado": 0,
            "percentual_valido": "100.00",
        }
    )

    assert resultado.permitido is True
