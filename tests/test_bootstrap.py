"""Bootstrap em blocos de meses (infra#TASK-31)."""

from datetime import date

from app.validacao.bootstrap import intervalo_em_blocos


def _meses(n_meses, por_mes, acerta_no_mes):
    janelas = []
    for m in range(n_meses):
        dia = date(2017 + m // 12, m % 12 + 1, 2)
        for _ in range(por_mes):
            janelas.append((dia, acerta_no_mes(m), 0.01 if acerta_no_mes(m) else -0.01))
    return janelas


def test_correlacao_dentro_do_mes_alarga_o_intervalo():
    # 60 meses x 20 ativos = 1.200 janelas, 55% de acerto; mas o mes inteiro
    # acerta ou erra junto - so ha 60 observacoes independentes, nao 1.200.
    janelas = _meses(60, 20, lambda m: m % 20 < 11)
    ic = intervalo_em_blocos(janelas, horizonte=21)["acerto"]
    largura_blocos = ic[1] - ic[0]
    largura_wilson_1200 = 2 * 1.96 * (0.55 * 0.45 / 1200) ** 0.5  # ~0,056
    assert largura_blocos > 3 * largura_wilson_1200


def test_deterministico_e_contem_a_media():
    janelas = _meses(48, 10, lambda m: m % 3 != 0)
    a = intervalo_em_blocos(janelas, horizonte=63)
    b = intervalo_em_blocos(janelas, horizonte=63)
    assert a == b
    media = sum(1 for _, acerto, _ in janelas if acerto) / len(janelas)
    assert a["acerto"][0] <= media <= a["acerto"][1]
    assert a["meses"] == 48


def test_sem_direcao_so_tem_intervalo_do_excesso():
    janelas = [(date(2020, m, 2), None, 0.02 * (m % 3 - 1)) for m in range(1, 13) for _ in range(5)]
    ic = intervalo_em_blocos(janelas, horizonte=21)
    assert ic["acerto"] is None
    assert ic["excesso"] is not None
