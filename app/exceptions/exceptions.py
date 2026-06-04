"""
Exceções customizadas para o projeto gerar-insights.
Permite tratamento mais específico de erros em diferentes camadas.
"""


class GerarInsightsException(Exception):
    """Exceção base do projeto"""
    pass


class QueueProcessingError(GerarInsightsException):
    """Erro ao processar mensagens da fila"""
    pass


class DatabaseError(GerarInsightsException):
    """Erro ao acessar o banco de dados"""
    pass


class InvalidAtivoError(GerarInsightsException):
    """Ativo inválido ou com dados incompletos"""
    pass


class TradingAnalysisError(GerarInsightsException):
    """Erro ao analisar e gerar insights de trading"""
    pass


class DatabaseConnectionError(Exception):
    pass