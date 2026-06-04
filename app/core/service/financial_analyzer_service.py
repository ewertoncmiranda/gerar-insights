from logging import Logger


class FinancialAnalyzerService:
    def __init__(self,logger: Logger):
        self.logger = logger

    def gerar_insight_fundamentalista(self, ativo: dict) -> dict:
        simbolo = ativo.get("symbol", "UNKNOWN")
        preco = ativo.get("regularMarketPrice")
        lpa = ativo.get("earningsPerShare")
        max52 = ativo.get("fiftyTwoWeekHigh")

        self.logger.info(f"Analisando ativo {simbolo} (Preço: {preco}, LPA: {lpa})")

        # Fallbacks caso falte dados fundamentais
        if not preco or not lpa or lpa <= 0:
            return self._resultado_nulo(simbolo)

        # 1. Filtro de Benjamin Graham
        # Fórmula clássica de Preço Justo: Valor = LPA * (8.5 + 2g)
        # Vamos assumir 'g' (crescimento estimado) = 5% ao ano como conservador
        crescimento_estimado = 5
        preco_justo_graham = lpa * (8.5 + 2 * crescimento_estimado)
        
        margem_seguranca = ((preco_justo_graham - preco) / preco_justo_graham) * 100

        # Recomendação Baseada na Margem de Segurança
        if margem_seguranca > 20:
            recomendacao = "COMPRA"
        elif 0 <= margem_seguranca <= 20:
            recomendacao = "NEUTRO"
        else:
            recomendacao = "VENDA"

        # Outros insights para armazenar no JSON extra
        detalhes = {
            "earnings_yield_percent": (lpa / preco) * 100,
            "desconto_maxima_52w_percent": ((max52 - preco) / max52) * 100 if max52 else None,
            "crescimento_projetado_utilizado": crescimento_estimado
        }

        return {
            "simbolo": simbolo,
            "preco_justo_graham": round(preco_justo_graham, 4),
            "margem_seguranca_percent": round(margem_seguranca, 4),
            "recomendacao": recomendacao,
            "detalhes_json": detalhes
        }

    def _resultado_nulo(self, simbolo: str) -> dict:
        return {
            "simbolo": simbolo,
            "preco_justo_graham": None,
            "margem_seguranca_percent": None,
            "recomendacao": "SEM DADOS",
            "detalhes_json": {"aviso": "Dados fundamentais insuficientes ou lucro negativo"}
        }
