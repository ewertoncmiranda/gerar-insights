# Gerar Insights - Motor Financeiro

Aplicacao Python responsavel por ser o cerebro analitico do ecossistema. Operando como um worker assincrono em loop infinito, consome snapshots de ativos brutos de uma fila SQS, aplica matematica financeira e grava historicos e insights em MySQL.

## Proposta de valor tecnico
--------------------
- Complementa o ecossistema com processamento em Python (flexibilidade para algoritmos de análise).
- Demonstra integração inter-linguagem (Java ↔ SQS ↔ Python).
- Mostra práticas: containerização, configuração por env, retries, logging e testes.

## RESPONSABILIDADES PRINCIPAIS

1. Consumo Robusto (SQS) - Le mensagens da fila sem gargalos, processa e apaga de forma eficiente.
2. Historico Bruto - Armazena snapshots de mercado diarios dos ativos na tabela historico_acoes.
3. Calculo de Insights - Aplica calculos financeiros (Preco Justo Benjamin Graham, Margem de Seguranca) e emite recomendacoes (COMPRA/VENDA/NEUTRO).

## TECNOLOGIAS E LIBS

- boto3: SDK AWS para acesso a SQS e DynamoDB
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
- Producer (pode ser o gestor-ativos-brutos ou outro sistema) coloca mensagens na fila SQS tratar-ativos.
- gerar-insights lê mensagens da fila SQS, executa as estratégias (mean reversion, momentum, valuation) e escreve resultados em MySQL.
- O Java app expõe métricas/health; se necessário, gerar-insights pode consultar o endpoint do Java para sincronização/health.

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

#### DynamoDB:
- DYNAMO_ENDPOINT (default: http://localstack:4566)
  Local: http://localhost:4566
- DYNAMO_TABLE_NAME (default: insights-refinados)

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
   DYNAMO_ENDPOINT=http://localhost:4566

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
      aws_config.py            Clientes boto3 (SQS, DynamoDB)
      database_config.py       SqlAlchemy engine
      config_logger.py         Setup de logs
    core/
      - Logica de indicadores e insights
    entrypoint/
      entrypoint_sqs.py        Consumer SQS
    external/
      - Integracao com servicos externos
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
