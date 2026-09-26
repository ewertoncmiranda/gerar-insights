"""Versao do conjunto de regras que gera a recomendacao.

O diario de sinais e o backtest comparam desempenho POR VERSAO: sem isso,
mudar um limiar em recommendation.py misturaria sinais de duas regras
diferentes no mesmo placar e nenhum dos dois numeros significaria nada.

Incremente sempre que mudar qualquer coisa que altere a recomendacao ou o
sinal tecnico para a mesma entrada:

  - limiares e ordem das regras em recommendation.py;
  - formula ou cenarios em valuation.py;
  - janelas e limiares em technical_context.py, technical_series.py e nas
    estrategias (momentum, reversao a media).

Mudanca de texto de insight, nome de campo ou refatoracao que nao mude a
saida NAO incrementa. Formato: AAAA.MM.DD-N (data da mudanca + sequencial).
"""

VERSAO_REGRA = "2026.09.26-1"
