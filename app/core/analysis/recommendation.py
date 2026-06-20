from app.core.analysis.market_snapshot import MarketSnapshot


class RecommendationPolicy:
    def evaluate(self, snapshot: MarketSnapshot, valuation: dict, technical_context: dict) -> dict:
        raw_context = technical_context["_raw"]
        recommendation = self.define_recommendation(valuation, raw_context["posicao_52w"])
        risk_level = self.classify_risk(
            valuation,
            raw_context["posicao_52w"],
            raw_context["amplitude_intradiaria"],
        )
        confidence = self.calculate_confidence(
            valuation,
            raw_context["posicao_52w"],
            raw_context["amplitude_intradiaria"],
        )

        return {
            "recomendacao": recommendation,
            "nivel_risco": risk_level,
            "confianca_score": confidence,
            "insights": self.generate_insights(snapshot, valuation, raw_context),
            "fatores_decisao": self.generate_decision_factors(snapshot, valuation, raw_context),
        }

    def define_recommendation(self, valuation: dict, range_52w_position: float | None) -> str:
        conservative_margin = valuation["cenarios_graham"]["conservador"]["margem_seguranca_percent"]
        base_margin = valuation["cenarios_graham"]["base"]["margem_seguranca_percent"]
        earnings_yield = valuation["earnings_yield"]

        if conservative_margin >= 20 and earnings_yield >= 12:
            return "COMPRA_FORTE"
        if base_margin >= 20 and earnings_yield >= 8:
            return "COMPRA_MODERADA"
        if base_margin < 0:
            return "VENDA_VALUATION"
        if range_52w_position is not None and range_52w_position >= 90 and base_margin <= 10:
            return "ALERTA_RISCO"
        return "MANTER"

    def classify_risk(
        self,
        valuation: dict,
        range_52w_position: float | None,
        intraday_range: float | None,
    ) -> str:
        conservative_margin = valuation["cenarios_graham"]["conservador"]["margem_seguranca_percent"]
        base_margin = valuation["cenarios_graham"]["base"]["margem_seguranca_percent"]

        if base_margin < 0 or (range_52w_position is not None and range_52w_position >= 90):
            return "ALTO"
        if conservative_margin < 0 or (intraday_range is not None and intraday_range >= 8):
            return "MEDIO"
        return "BAIXO"

    def calculate_confidence(
        self,
        valuation: dict,
        range_52w_position: float | None,
        intraday_range: float | None,
    ) -> int:
        score = 50
        conservative_margin = valuation["cenarios_graham"]["conservador"]["margem_seguranca_percent"]
        base_margin = valuation["cenarios_graham"]["base"]["margem_seguranca_percent"]
        earnings_yield = valuation["earnings_yield"]

        if conservative_margin >= 20:
            score += 20
        elif conservative_margin >= 0:
            score += 10
        elif base_margin < 0:
            score -= 20

        if earnings_yield >= 12:
            score += 15
        elif earnings_yield >= 8:
            score += 8
        elif earnings_yield < 6:
            score -= 10

        if range_52w_position is not None:
            if 25 <= range_52w_position <= 75:
                score += 5
            elif range_52w_position >= 90:
                score -= 10

        if intraday_range is not None and intraday_range >= 8:
            score -= 5

        return max(0, min(100, score))

    def generate_insights(self, snapshot: MarketSnapshot, valuation: dict, raw_context: dict) -> list[dict]:
        insights = []
        conservative_margin = valuation["cenarios_graham"]["conservador"]["margem_seguranca_percent"]
        base_margin = valuation["cenarios_graham"]["base"]["margem_seguranca_percent"]
        earnings_yield = valuation["earnings_yield"]

        if conservative_margin >= 20:
            insights.append({
                "tipo": "MARGEM_SEGURANCA",
                "severidade": "POSITIVO",
                "mensagem": "A margem de seguranca permanece acima de 20% mesmo no cenario conservador.",
            })
        elif base_margin >= 20:
            insights.append({
                "tipo": "MARGEM_SEGURANCA",
                "severidade": "POSITIVO_MODERADO",
                "mensagem": "A margem de seguranca e atrativa no cenario base, mas depende de crescimento moderado.",
            })
        elif base_margin < 0:
            insights.append({
                "tipo": "VALUATION",
                "severidade": "NEGATIVO",
                "mensagem": "O preco atual esta acima do valor justo no cenario base.",
            })

        if earnings_yield >= 12:
            insights.append({
                "tipo": "EARNINGS_YIELD",
                "severidade": "POSITIVO",
                "mensagem": "Earnings yield acima de 12% indica retorno de lucro elevado para padrao Brasil.",
            })
        elif earnings_yield < 6:
            insights.append({
                "tipo": "EARNINGS_YIELD",
                "severidade": "NEGATIVO",
                "mensagem": "Earnings yield abaixo de 6% exige crescimento forte para justificar o preco.",
            })

        if snapshot.price_earnings is not None and snapshot.price_earnings > 20:
            insights.append({
                "tipo": "PRECO_LUCRO",
                "severidade": "ATENCAO",
                "mensagem": "P/L acima de 20 sugere valuation exigente e maior dependencia de crescimento.",
            })

        range_52w_position = raw_context["posicao_52w"]
        if range_52w_position is not None and range_52w_position >= 85:
            insights.append({
                "tipo": "CONTEXTO_TECNICO",
                "severidade": "ATENCAO",
                "mensagem": "O ativo esta proximo da maxima de 52 semanas; entrada tardia aumenta risco de assimetria ruim.",
            })
        elif range_52w_position is not None and range_52w_position <= 25:
            insights.append({
                "tipo": "CONTEXTO_TECNICO",
                "severidade": "NEUTRO",
                "mensagem": "O ativo esta proximo da minima de 52 semanas; pode indicar desconto ou deterioracao de fundamentos.",
            })

        intraday_range = raw_context["amplitude_intradiaria"]
        if intraday_range is not None and intraday_range >= 8:
            insights.append({
                "tipo": "VOLATILIDADE",
                "severidade": "ATENCAO",
                "mensagem": "Amplitude intradiaria elevada sugere volatilidade relevante no pregao.",
            })

        if not insights:
            insights.append({
                "tipo": "SEM_SINAL_FORTE",
                "severidade": "NEUTRO",
                "mensagem": "Nenhum sinal forte foi identificado com os dados atuais.",
            })

        return insights

    def generate_decision_factors(self, snapshot: MarketSnapshot, valuation: dict, raw_context: dict) -> dict:
        positive = []
        negative = []
        neutral = []
        conservative_margin = valuation["cenarios_graham"]["conservador"]["margem_seguranca_percent"]
        base_margin = valuation["cenarios_graham"]["base"]["margem_seguranca_percent"]
        earnings_yield = valuation["earnings_yield"]

        if conservative_margin >= 20:
            positive.append("margem_conservadora_acima_20")
        elif base_margin >= 20:
            positive.append("margem_base_acima_20")
        elif base_margin < 0:
            negative.append("preco_acima_valor_justo_base")

        if earnings_yield >= 12:
            positive.append("earnings_yield_acima_12")
        elif earnings_yield < 6:
            negative.append("earnings_yield_abaixo_6")

        if snapshot.price_earnings is not None:
            if snapshot.price_earnings < 8:
                neutral.append("pl_baixo_pode_indicar_desconto_ou_risco")
            elif snapshot.price_earnings > 20:
                negative.append("pl_acima_20")

        range_52w_position = raw_context["posicao_52w"]
        if range_52w_position is not None:
            if range_52w_position >= 85:
                negative.append("proximo_maxima_52w")
            elif range_52w_position <= 25:
                neutral.append("proximo_minima_52w")

        return {
            "positivos": positive,
            "negativos": negative,
            "neutros": neutral,
        }
