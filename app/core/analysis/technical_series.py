from statistics import mean, pstdev

from app.core.analysis.number_utils import round_metric


class TechnicalSeriesAnalyzer:
    def analyze(self, closes: list[float], volumes: list[float]) -> dict | None:
        if len(closes) < 2:
            return None

        media_movel = mean(closes)
        desvio_padrao = pstdev(closes)
        ultimo_fechamento = closes[-1]
        z_score = (ultimo_fechamento - media_movel) / desvio_padrao if desvio_padrao else 0.0

        score_volume = None
        if volumes:
            media_volume = mean(volumes)
            if media_volume:
                score_volume = volumes[-1] / media_volume

        return {
            "media_movel": round_metric(media_movel),
            "z_score_fechamento": round_metric(z_score),
            "score_volume": round_metric(score_volume),
            "amostras": len(closes),
        }
