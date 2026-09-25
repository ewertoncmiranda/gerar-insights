"""
Testes unitários para TechnicalSeriesAnalyzer.
Valida o calculo de media movel, z-score e score de volume sobre uma serie de closes/volumes.
"""

from app.core.analysis.technical_series import TechnicalSeriesAnalyzer


class TestTechnicalSeriesAnalyzer:

    def test_amostra_insuficiente_retorna_none(self):
        analyzer = TechnicalSeriesAnalyzer()
        assert analyzer.analyze([5.0], [1000]) is None
        assert analyzer.analyze([], []) is None

    def test_serie_constante_tem_z_score_zero(self):
        analyzer = TechnicalSeriesAnalyzer()
        closes = [10.0] * 20
        volumes = [1000] * 20

        resultado = analyzer.analyze(closes, volumes)

        assert resultado["media_movel"] == 10.0
        assert resultado["z_score_fechamento"] == 0.0
        assert resultado["score_volume"] == 1.0
        assert resultado["amostras"] == 20

    def test_score_volume_none_quando_sem_volumes(self):
        analyzer = TechnicalSeriesAnalyzer()
        closes = [10.0, 11.0, 12.0]

        resultado = analyzer.analyze(closes, [])

        assert resultado["score_volume"] is None

    def test_ultimo_fechamento_acima_da_media_gera_z_score_positivo(self):
        analyzer = TechnicalSeriesAnalyzer()
        closes = [5.0] * 19 + [10.0]
        volumes = [1000] * 19 + [2000]

        resultado = analyzer.analyze(closes, volumes)

        assert resultado["media_movel"] < 10.0
        assert resultado["z_score_fechamento"] > 0
        assert resultado["score_volume"] > 1.0
