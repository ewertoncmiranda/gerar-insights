# Gerar Insights - Motor Financeiro

Aplicacao Python responsavel por ser o cerebro analitico do ecossistema. Operando como um worker assincrono em loop infinito, consome snapshots de ativos brutos de uma fila SQS, aplica matematica financeira e grava historicos e insights em MySQL.

## Proposta de valor tecnico
--------------------
- Complementa o ecossistema com processamento em Python (flexibilidade para algoritmos de análise).
- Demonstra integração inter-linguagem (Java ↔ SQS ↔ Python).
- Mostra práticas: containerização, configuração por env, retries, logging e testes.

## RESPONSABILIDADES PRINCIPAIS

1. Consumo Robusto (SQS) - Le mensagens de duas filas (cotacoes e series historicas) sem gargalos, processa e apaga de forma eficiente.
2. Historico Bruto - Armazena snapshots de mercado diarios dos ativos na tabela historico_acoes e os candles OHLCV na tabela serie_historica.
3. Calculo de Insights - Aplica calculos financeiros (Preco Justo Benjamin Graham, Margem de Seguranca) e sinal tecnico (media movel, z-score, score de volume via Momentum/Mean Reversion) e emite sinais quantitativos para estudo, sempre com aviso legal; nao emite recomendacao de investimento.

## TECNOLOGIAS E LIBS

- boto3: SDK AWS para acesso a SQS
- SQLAlchemy + PyMySQL: Gerenciamento de conexoes e persistencia em MySQL
- python-dotenv: Carregamento de variaveis de ambiente via arquivo .env
- python-json-logger: Logs estruturados

## CONFIGURACAO CENTRALIZADA

### Todas as configuracoes estao centralizadas em app/config/settings.py seguindo principios SOLID e clean code:
- Leitura de variaveis de ambiente com defaults seguros
- Validacao de variaveis obrigatorias
- Logging de configuracao na inicializacao

### Observabilidade e logs
- O worker faz logs em stdout; quando containerizado, utilize docker logs gerar-insights.
- Configurar LOG_LEVEL=DEBUG para debug mais detalhado.
### Fluxo entre gestor-ativos-brutos e gerar-insights
- `gestor-ativos-brutos` coloca cotações na fila SQS `tratar-ativos` e, quando chamado via `/ativos/robusto/{ativo}`, também publica a série histórica OHLCV na fila `sqs-registrar-series-historicas`.
- `gerar-insights` consome as duas filas: cotações alimentam o insight fundamentalista (Graham) e o sinal técnico (lido de `serie_historica`); a série histórica alimenta a tabela `serie_historica` usada por esse sinal técnico.
- O resultado combinado (fundamentos + sinal técnico) é gravado numa única linha de `insight_acao`, que o `gestor-ativos-brutos` consolida em `GET /analises/{simbolo}/analise`.
- O Java app expõe métricas/health; se necessário, gerar-insights pode consultar o endpoint do Java para sincronização/health.

## Sinal técnico sobre séries históricas

Além do insight fundamentalista (Graham), cada cotação processada também calcula um sinal técnico a partir dos candles já persistidos em `serie_historica`:

- **Média móvel (20 candles)**, **z-score do último fechamento** e **score de volume** (`volume atual / média do volume na janela`), calculados em `TechnicalSeriesAnalyzer` (`app/core/analysis/technical_series.py`).
- Esses números alimentam `MomentumStrategy` e `MeanReversionStrategy` (`app/core/strategies/`), que já existiam no projeto mas nunca eram chamadas — `SerieTecnicaService` (`app/core/service/serie_tecnica_service.py`) é quem orquestra tudo isso.
- Quando o símbolo ainda não tem 20 candles em `serie_historica`, o sinal é omitido (não é erro) — o insight fundamentalista continua sendo gerado normalmente.
- O resultado é anexado ao `detalhes_json` do insight (bloco `contexto_tecnico_serie`, mais os campos `media_movel`, `z_score_fechamento` e `score_volume` no nível de topo, para que o lado Java consolide automaticamente sem nenhuma mudança de código).

## Dependência de infraestrutura (`infra-b3-ecossystem`)

O sinal técnico depende de dois recursos que **não são provisionados por este repositório**, e sim pelo repositório `infra-b3-ecossystem` anexado ao ecossistema:

- **Fila SQS `sqs-registrar-series-historicas`**, definida via Terraform em `infra/main.tf` (módulo `sqs`, entrada `registrar_series_historicas`).
- **Tabela MySQL `serie_historica`**, criada em `mysql-init/1 - schema.sql`.

Sem aplicar esse Terraform (`terraform apply` no diretório `infra/`) e sem rodar esse script de inicialização do MySQL, o segundo consumidor de fila registrado em `main.py` não tem fila para ler nem tabela para gravar — o worker sobe normalmente, mas o sinal técnico nunca é calculado (fica sempre ausente, como se não houvesse candles).

### Problemas comuns e solução
#### Worker não consome mensagens:
- Verifique LOCALSTACK_ENDPOINT e QUEUE_NAME.
- Confirme que a fila existe no LocalStack: awslocal sqs list-queues.
#### Erros de persistência:
- Verifique DB_USER/DB_PASS e se o banco está acessível.
- Ao rodar dentro do Compose, use host mysql:3306; se rodar localmente e MySQL for container com mapeamento 3305, ajuste o host/porta na string de conexão no código.
Observações finais
- Estes README seguem o estilo prático/operacional esperado por imagens no Docker Hub: descrição curta, variáveis de ambiente destacadas, instruções de execução e interoperabilidade entre componentes.
- Se desejar, adapto cada README para incluir badges (build/test) e instruções adicionais de CI/CD, ou gero os arquivos fisicamente no repositório (no momento sou somente leitura: colar o conteúdo acima em cada `README.md` fará o trabalho).

Quer que eu:
- Gere um `.env` alternativo pronto para rodar via Docker Compose com variáveis já ajustadas para container-network (DB_URL com `mysql:3306` e `SERVER_PORT=8091`)?
- Adicione exemplos de comandos `awslocal`/`aws` para criar/verificar fila?

## VARIAVEIS DE AMBIENTE

### Defaults para docker: localstack:4566, mysql:3306
#### Para execucao local: defina variaveis apontando para localhost

AWS/LocalStack:
- LOCALSTACK_ENDPOINT (default: http://localstack:4566)
  Local: http://localhost:4566
- QUEUE_NAME (default: tratar-ativos)
- AWS_REGION (default: sa-east-1)
- AWS_ACCESS_KEY_ID (default: test)
- AWS_SECRET_ACCESS_KEY (default: test)

##### Banco de Dados:
- DB_DRIVER (default: mysql+pymysql)
- DB_HOST (default: mysql)
  Local: localhost
- DB_PORT (default: 3306)
  Local: 3305
- DB_USER (default: spring)
- DB_PASS (default: spring123)
- DB_NAME (default: minha_base)

#### Retry/Timeout:
- RETRY_ATTEMPTS (default: 3)
- RETRY_DELAY (default: 10 segundos)

##### QUICK START - EXECUCAO LOCAL

## Prerequisitos: LocalStack e MySQL rodando em localhost

1. Criar ambiente virtual:     
    python -m venv .venv
    source .venv/bin/activate
    pip install -r gerar-insights/requirements.txt

2. Instalar dependencias:
   pip install -r requirements.txt

3. Criar arquivo .env.local com configuracoes para localhost:
   DB_HOST=localhost
   DB_PORT=3305
   LOCALSTACK_ENDPOINT=http://localhost:4566

4. Executar:
   python main.py

#### EXECUCAO VIA DOCKER

### Na raiz do projeto:
   docker-compose up --build -d gerar-insights

O container automaticamente usa rede interna docker (localstack:4566, mysql:3306).

#### ESTRUTURA DO PROJETO

gerar-insights/
  app/
    config/
      settings.py              Configuracoes centralizadas (SOLID)
      aws_config.py            Clientes boto3 (SQS)
      database_config.py       SqlAlchemy engine
      config_logger.py         Setup de logs
    core/
      core_processor.py        Consumo das filas SQS (ativos + series historicas) e orquestracao
      analysis/                Calculos puros: valuation Graham, contexto tecnico, sinal tecnico de serie
      strategies/               Momentum e Mean Reversion (usadas pelo sinal tecnico de serie)
      service/                  Servicos de aplicacao (FinancialAnalyzerService, SerieHistoricaService, SerieTecnicaService, PersistenciaHistoricoService)
      mapper/                   Conversao de payload bruto para objetos de dominio
    external/
      database/                 Entidades e repositorios SQLAlchemy
  main.py                       Ponto de entrada
  requirements.txt              Dependencias
  Dockerfile                    Imagem Docker

#### TESTES

Execute testes automatizados:
   pytest tests/ -v

### NOTAS IMPORTANTES

- Arquivo .env.local nao deve ser commitado (.gitignore ja ignora)
- Senhas/tokens nao devem ser hard-coded em producao
- Use secrets manager (AWS Secrets Manager, Vault) em producao
- Verifique logs iniciais para confirmar que configuracao foi carregada

Observações finais
- Estes README seguem o estilo prático/operacional esperado por imagens no Docker Hub: descrição curta, variáveis de ambiente destacadas, instruções de execução e interoperabilidade entre componentes.
- Se desejar, adapto cada README para incluir badges (build/test) e instruções adicionais de CI/CD, ou gero os arquivos fisicamente no repositório (no momento sou somente leitura: colar o conteúdo acima em cada `README.md` fará o trabalho).

Quer que eu:
- Gere um `.env` alternativo pronto para rodar via Docker Compose com variáveis já ajustadas para container-network (DB_URL com `mysql:3306` e `SERVER_PORT=8091`)?
- Adicione exemplos de comandos `awslocal`/`aws` para criar/verificar fila?# gerar-insights
