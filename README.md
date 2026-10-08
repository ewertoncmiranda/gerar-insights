# Gerar Insights

Worker Python do ecossistema B3 responsável por transformar cotações e séries
históricas em dados analíticos persistidos no MySQL. O serviço não expõe API
HTTP: ele consome mensagens do SQS, executa cálculos financeiros e grava os
resultados para consulta pelos demais componentes.

> A especificação funcional, as decisões técnicas e o andamento das tarefas
> ficam em [`SPEC.md`](SPEC.md), que é a fonte de verdade do projeto.

## Fluxo principal

O processo iniciado por `main.py` consome duas filas:

- `tratar-ativos`: recebe snapshots de ativos, grava `historico_acoes` e produz
  o insight fundamentalista;
- `sqs-registrar-series-historicas`: recebe candles OHLCV e alimenta
  `serie_historica`.

O sinal principal usa valuation de Graham e margem de segurança. Quando há
histórico suficiente, o payload também inclui um contexto técnico separado,
com média móvel, z-score e volume relativo. Esse contexto não altera o sinal
fundamentalista principal. O contrato público usa rótulos neutros e inclui
aviso de que o conteúdo não constitui recomendação de investimento.

O schema do banco e as filas são provisionados pelo repositório de
infraestrutura. Este worker não executa migrações ao iniciar.

## Requisitos

- Python 3.11;
- MySQL acessível com o schema do ecossistema aplicado;
- AWS SQS ou LocalStack com as duas filas criadas.

## Configuração

Copie `.env.example` para um arquivo local não versionado e ajuste-o ao seu
ambiente. As configurações são centralizadas em `app/config/settings.py`.
As variáveis principais são:

- `ENVIRONMENT` e `ENV_FILE`;
- `LOCALSTACK_ENDPOINT`, `AWS_REGION`, `AWS_ACCESS_KEY_ID` e
  `AWS_SECRET_ACCESS_KEY`;
- `QUEUE_NAME` e `HISTORICAL_SERIES_QUEUE_NAME`;
- `DB_DRIVER`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS` e `DB_NAME`;
- `RETRY_ATTEMPTS`, `RETRY_DELAY` e `LOG_LEVEL`.

Em execução local, `DB_HOST` e `LOCALSTACK_ENDPOINT` normalmente apontam para
`localhost`. Dentro da rede Docker do ecossistema, use os nomes dos serviços.

## Execução local

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python main.py
```

Ative o ambiente virtual conforme o seu sistema operacional antes de instalar
as dependências. O worker permanece em execução enquanto consome as filas.

## Docker

```bash
docker build -t gerar-insights .
docker run --rm --env-file .env.local gerar-insights
```

O container ainda precisa alcançar o MySQL e o SQS/LocalStack configurados no
arquivo de ambiente. No ecossistema completo, a rede e esses serviços são
orquestrados pelo repositório de infraestrutura.

## Comandos auxiliares

Além do worker principal, o projeto contém rotinas executáveis como módulos:

```bash
python -m app.insights_diarios
python -m app.insights_diarios --recuperar
python -m app.validacao.diario registrar
python -m app.validacao.diario avaliar
python -m app.validacao.backtest
python -m app.fatores calcular --desde AAAA-MM
```

Consulte `--help` quando disponível e a seção correspondente de `SPEC.md`
antes de executar rotinas que persistem dados.

## Testes e qualidade

Instale também as dependências de desenvolvimento:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m pytest tests -q --cov=app/core/analysis --cov-report=term-missing --cov-fail-under=90
python -m ruff check app tests
```

Os testes de domínio ficam principalmente em `tests/analysis`, complementados
pelos testes de integração e regressão em `tests/`.

## Estrutura

```text
app/
  config/              configuração, banco, AWS e logging
  core/
    analysis/          regras e cálculos puros do domínio
    mapper/            conversão dos payloads de entrada
    service/           orquestração dos casos de uso
    strategies/        estratégias técnicas auxiliares
  external/database/   entidades e repositórios SQLAlchemy
main.py                 ponto de entrada do worker
tests/                  suíte automatizada
SPEC.md                 requisitos, decisões e plano de evolução
```

## Observabilidade e segurança

Os logs estruturados são enviados para `stdout`; ajuste `LOG_LEVEL` para mudar
o nível de detalhe. Não versione arquivos `.env`, senhas ou tokens. Em produção,
injete credenciais por um mecanismo de secrets apropriado ao ambiente.
