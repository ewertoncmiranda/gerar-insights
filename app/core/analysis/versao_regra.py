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

# Historico:
#   2026.09.26-1  Graham sem juros, LPA do snapshot, venda com margem < 0.
#   2026.09.27-1  Y = Selic meta (ISS-F1, DEC-02); LPA normalizado e Graham
#                 Number (ISS-F2); faixa neutra e limiares em limiares.py
#                 (ISS-F3); ver DEC-07 para a calibracao.
VERSAO_REGRA = "2026.09.27-1"
