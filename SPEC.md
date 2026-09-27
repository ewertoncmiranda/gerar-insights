# SPEC — gerar-insights (Motor Financeiro)

| Campo | Valor |
|---|---|
| Versão da spec | 1.0.0 |
| Data | 2026-09-25 |
| Status | Ativa — baseline do estado atual + backlog planejado |
| Branch analisada | `feature-migrate` (último commit `c432f9d`) |
| Alterações não commitadas | feature de série histórica (ver `ISS-13`) |
| Specs relacionadas | `infra-b3-ecossytem/SPEC.md` (ecossistema, Docker, contratos `CTR-` e problemas de integração `INT-`) · `gestor-ativos-brutos/SPEC.md` (produtor SQS e leitor de `insight_acao`) |
| Público | Desenvolvedores humanos e agentes de IA (Codex, ChatGPT, Claude ou outros) |

---

## 1. Como usar este arquivo (protocolo para agentes)

Este é o **documento-fonte** do projeto, no modelo Spec Driven Development (SDD). Código, testes e planos derivam daqui.

**Fluxo obrigatório:** `Spec → Plano → Tarefas → Implementação → Verificação → Atualizar Spec`.

Regras:

1. Antes de alterar código, leia as seções 2 a 7. Toda alteração deve estar ligada a um ID (`REQ-`, `NFR-`, `ISS-` ou `TASK-`).
2. **IDs são estáveis.** Nunca renumere nem apague um ID; para descontinuar, mude o status para `DESCARTADO` com justificativa.
3. Status válidos: `ABERTO`, `EM_ANDAMENTO`, `BLOQUEADO`, `CONCLUIDO`, `DESCARTADO` (tarefas/problemas) e `IMPLEMENTADO`, `PARCIAL`, `PLANEJADO` (requisitos).
4. Ao concluir uma `TASK-`, atualize o status, registre a data e cite o commit/PR na coluna "Notas".
5. Decisões de design ou de negócio viram uma entrada `DEC-` (seção 9). Não tome decisões marcadas como abertas sem registrar a escolha.
6. Não invente requisitos: se algo não está aqui, proponha um novo item (`REQ-`/`TASK-`) com status `PLANEJADO`/`ABERTO` em vez de implementá-lo direto.
7. Critérios de aceite usam o formato **Dado / Quando / Então** e devem virar testes automatizados sempre que possível.
8. Mudanças em regras financeiras (seção 5) exigem incrementar `versao_payload` e atualizar esta spec no mesmo PR.

---

## 2. Visão do produto (funcional)

`gerar-insights` é o **cérebro analítico** de um ecossistema de acompanhamento de ações da B3. É um worker Python sem interface nem API HTTP que roda em loop infinito:

1. Um produtor (app Java `gestor-ativos-brutos`) coleta dados de mercado da **BRAPI** e publica mensagens em filas **SQS** (LocalStack em desenvolvimento).
2. Este worker consome as filas, aplica matemática financeira e grava resultados em **MySQL**.
3. Outros sistemas leem as tabelas de insights para exibir recomendações.

### 2.1 Fila `tratar-ativos` (snapshot de ativo)
- Entrada: cotação atual de um ativo (formato BRAPI `quote`).
- Ações:
  1. grava o snapshot bruto em `historico_acoes`;
  2. calcula valuation (Graham), earnings yield e contexto técnico de 52 semanas;
  3. gera recomendação, nível de risco, score de confiança, insights textuais e fatores de decisão;
  4. grava o resultado em `insight_acao` (colunas-resumo + `detalhes_json`).

### 2.2 Fila `sqs-registrar-series-historicas` (série histórica)
- Entrada: resposta BRAPI com `results[].data.historicalDataPrice` (candles).
- Ação: *upsert* de candles diários em `serie_historica` com chave única `(simbolo, data_pregao, intervalo)`. A data do pregão é derivada do timestamp Unix convertido para UTC-3 (Brasília), com fallback para `dataFormatada` (`dd/mm/aaaa`).
- Observação: os dados históricos entram como sinais técnicos separados (momentum, reversão à média), não na recomendação de valuation (ver `ISS-F5`).

---

## 3. Arquitetura técnica

### 3.1 Fluxo

```
 BRAPI ──> gestor-ativos-brutos (Java) ──> SQS (LocalStack :4566)
                                             │   ├─ tratar-ativos
                                             │   └─ sqs-registrar-series-historicas
                                             v
                               gerar-insights (Python, loop infinito)
                                 main.py
                                  └─ CoreProcessor.consume_queues
                                      ├─ processar_mensagem_ativo
                                      │    ├─ PersistenciaHistoricoService ─> historico_acoes
                                      │    └─ FinancialAnalyzerService
                                      │         ├─ ValuationAnalyzer (Graham)
                                      │         ├─ TechnicalContextAnalyzer
                                      │         ├─ RecommendationPolicy
                                      │         └─ InsightPayloadBuilder ─> insight_acao
                                      └─ processar_mensagem_serie_historica
                                           └─ SerieHistoricaService ─> serie_historica (upsert)
                                             v
                                       MySQL (:3305 local / mysql:3306 docker)
```

### 3.2 Mapa de módulos

| Caminho | Responsabilidade |
|---|---|
| `main.py` | Ponto de entrada: cria `Settings` e `CoreProcessor`, garante as filas e inicia o consumo |
| `app/config/settings.py` | Configuração centralizada via env/dotenv; `ENVIRONMENT=docker\|container\|compose` troca os hosts padrão |
| `app/config/aws_config.py` | Fábrica do cliente boto3 SQS |
| `app/config/database_config.py` | Engine SQLAlchemy, espera o MySQL (retry), `sessionmaker`, `Base` declarativa |
| `app/config/config_logger.py` | Logger `sqs-consumer` em stdout |
| `app/core/core_processor.py` | Loop de consumo, roteamento por fila, transação por mensagem, delete/retry |
| `app/core/analysis/` | **Lógica financeira pura** (sem I/O): snapshot, valuation, contexto técnico, recomendação, payload |
| `app/core/service/` | Orquestração: análise, persistência de histórico e série histórica |
| `app/core/mapper/` | Conversão de payload BRAPI → objetos de domínio (`SnapshotAcao`, `CandleDiario`) |
| `app/core/strategies/` | Estratégias Mean Reversion, Momentum e Valuation — **não conectadas ao fluxo** |
| `app/external/database/` | Entidades ORM e repositórios |
| `app/exceptions/exceptions.py` | Hierarquia de exceções — **não usada** |
| `tests/` | Pytest — **parcialmente quebrado** (ver `ISS-03`) |
| `.github/workflows/` | CI: auto-PR `feature*` → `develop`; push em `develop` → build/push Docker Hub |

### 3.3 Stack
Python 3.11 (imagem `python:3.11-slim`), boto3/botocore, SQLAlchemy ≥ 2, PyMySQL, python-dotenv, pydantic (declarado, não usado), python-json-logger (declarado, não usado), requests (declarado, não usado).

### 3.4 Semântica de processamento de mensagens (`CoreProcessor._consumir_fila`)

| Resultado do handler | Ação na mensagem |
|---|---|
| Sucesso | `session.commit()` e `delete_message` |
| `JSONDecodeError`, `ValueError`, `TypeError` | Considerado payload inválido: **descartado** (delete) |
| Qualquer outra exceção | `rollback`, mensagem **mantida** para nova tentativa (visibility timeout) |
| Erro no `receive_message` | Log, espera de 5 s e segue o loop |

Polling: `MaxNumberOfMessages=10`, `WaitTimeSeconds=2`, filas consumidas em sequência; se não houver mensagem em nenhuma fila, dorme 5 s.

### 3.5 Configuração (variáveis de ambiente)

| Variável | Padrão local | Padrão docker |
|---|---|---|
| `ENVIRONMENT` | `local` | `docker` |
| `ENV_FILE` | `.env.local` (procura na raiz e em `env/`) | — |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | `http://localstack:4566` |
| `QUEUE_NAME` | `tratar-ativos` | idem |
| `HISTORICAL_SERIES_QUEUE_NAME` | `sqs-registrar-series-historicas` | idem |
| `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `sa-east-1` / `test` / `test` | idem |
| `DB_DRIVER` | `mysql+pymysql` | idem |
| `DB_HOST` / `DB_PORT` | `localhost` / `3305` | `mysql` / `3306` |
| `DB_USER` / `DB_PASS` / `DB_NAME` | `spring` / `spring123` / `minha_base` | idem |
| `RETRY_ATTEMPTS` / `RETRY_DELAY` | `3` / `10` s | idem |
| `LOG_LEVEL` | `INFO` (**lido, mas ignorado** — `ISS-08`) | idem |
| `DYNAMO_ENDPOINT` / `DYNAMO_TABLE_NAME` | mencionadas; DynamoDB **não é usado** | — |

Regra especial: em ambiente local, se `DB_HOST=mysql`, ele vira `localhost` e a porta 3306 vira 3305.

---

## 4. Contratos de dados

### 4.1 Entrada — fila `tratar-ativos` (campos BRAPI consumidos)

```json
{
  "symbol": "PETR4",
  "regularMarketPrice": 38.50,
  "regularMarketOpen": 38.10,
  "regularMarketPreviousClose": 38.00,
  "regularMarketDayHigh": 38.90,
  "regularMarketDayLow": 37.95,
  "regularMarketVolume": 45000000,
  "marketCap": 500000000000,
  "fiftyTwoWeekLow": 30.10,
  "fiftyTwoWeekHigh": 42.30,
  "priceEarnings": 5.2,
  "earningsPerShare": 7.40
}
```

Todos os campos são opcionais no parse. Sem `regularMarketPrice` ou com `earningsPerShare <= 0`, o resultado é `SEM_DADOS`.

### 4.2 Entrada — fila `sqs-registrar-series-historicas`

```json
{
  "results": [{
    "symbol": "PETR4",
    "data": {
      "usedInterval": "1d",
      "usedRange": "3mo",
      "historicalDataPrice": [
        {"date": 1758240000, "open": 38.1, "high": 38.9, "low": 37.9,
         "close": 38.5, "adjustedClose": 38.5, "volume": 45000000}
      ]
    }
  }]
}
```

Também é aceito um único resultado na raiz (`{"symbol":..., "data": {...}}`). Sem `symbol` (ou `requestedSymbol`) → `ValueError` (mensagem descartada).

### 4.3 Tabelas escritas

| Tabela | Entidade | Chave / restrições | Observações |
|---|---|---|---|
| `historico_acoes` | `HistoricoAcaoEntity` | PK `id` | Um registro por mensagem; **sem chave natural** (duplicidade possível) |
| `insight_acao` | `InsightEntity` | PK `id` | `simbolo`, `data_analise`, `preco_justo_graham`, `margem_seguranca_percent`, `recomendacao` (varchar 20), `detalhes_json` |
| `serie_historica` | `SerieHistoricaEntity` | UNIQUE `(simbolo, data_pregao, intervalo)` | Upsert; `fonte` fixa em `BRAPI` |
| `ativos` | `AtivoEntity` | PK `id` | Mapeada, **não usada** pelo worker |

O schema não é criado pelo worker (ver `ISS-07`).

### 4.4 Saída — `detalhes_json` (versão `2.0`)

```
versao_payload: "2.0"
resumo: { recomendacao, nivel_risco, confianca_score, cenario_referencia: "base" }
snapshot_mercado: { preco, abertura, fechamento_anterior, maxima_dia, minima_dia, volume,
                    valor_mercado, preco_lucro, lucro_por_acao, minima_52w, maxima_52w }
valuation: { earnings_yield_percent, classificacao_pl, classificacao_earnings_yield,
             cenarios_graham: { conservador|base|otimista: { crescimento_percent,
               multiplo_lucro_implicito, preco_justo, margem_seguranca_percent } } }
contexto_tecnico: { variacao_desde_abertura_percent, variacao_vs_fechamento_anterior_percent,
                    amplitude_intradiaria_percent, posicao_range_52w_percent,
                    desconto_maxima_52w_percent, distancia_minima_52w_percent, zona_52w }
insights: [ { tipo, severidade, mensagem } ]
fatores_decisao: { positivos: [], negativos: [], neutros: [] }
earnings_yield_percent, desconto_maxima_52w_percent, crescimento_projetado_utilizado   (primeiro nível — CONTRATO, ver abaixo)
```

> **Atenção (contrato `infra#CTR-03`):** o `gestor-ativos-brutos` lê `insight_acao` e calcula médias **apenas dos campos numéricos de primeiro nível** de `detalhes_json`. Os três campos acima parecem duplicados, mas **não podem ser removidos ou renomeados** sem uma nova versão do contrato. Ele também conta recomendações pelo valor exato da coluna `recomendacao` (ver `infra#INT-01`).

Com `SEM_DADOS`: `{ "versao_payload": "2.0", "aviso": "Dados fundamentais insuficientes ou lucro negativo" }`.

---

## 5. Regras de negócio financeiras (comportamento atual)

Notação: `P` = preço atual, `LPA` = lucro por ação, `g` = crescimento anual esperado (%). Valores arredondados a 4 casas decimais.

### 5.1 Pré-condição
`P` precisa ser verdadeiro (não nulo e diferente de zero) e `LPA > 0`; caso contrário a recomendação é `SEM_DADOS` e nenhum cálculo é feito.

### 5.2 Valuation (Graham) — `app/core/analysis/valuation.py`
- Múltiplo implícito: `M = 8,5 + 2g`
- Preço justo: `V = LPA × M`
- Margem de segurança: `MS = (V − P) / V × 100`
- Cenários: `conservador g=0` (M=8,5), `base g=3` (M=14,5), `otimista g=5` (M=18,5). As colunas `preco_justo_graham` e `margem_seguranca_percent` usam o cenário **base**.

### 5.3 Múltiplos
- Earnings yield: `EY = LPA / P × 100` → `ATRATIVO ≥ 12`, `RAZOAVEL ≥ 8`, `BAIXO ≥ 6`, senão `MUITO_BAIXO`.
- P/L (`priceEarnings` do payload): `≤ 0 ou nulo → NAO_DISPONIVEL`, `< 8 BAIXO_COM_ATENCAO`, `≤ 15 SAUDAVEL`, `≤ 20 ESTICADO`, `> 20 EXIGENTE`.

### 5.4 Contexto técnico — `app/core/analysis/technical_context.py`
- Posição no range de 52 semanas: `(P − min52) / (max52 − min52) × 100` (nula se max ≤ min)
- Desconto da máxima: `(max52 − P) / max52 × 100`; distância da mínima: `(P − min52) / min52 × 100`
- Variação vs abertura e vs fechamento anterior (%)
- Amplitude intradiária: `(máxima_dia − mínima_dia) / P × 100`
- Zona: `≤ 25 PROXIMO_DA_MINIMA`, `≥ 85 PROXIMO_DA_MAXIMA`, senão `MEIO_DO_RANGE`

### 5.5 Recomendação — `app/core/analysis/recommendation.py`
Avaliada na ordem abaixo; vale a primeira regra verdadeira:

| # | Condição | Recomendação |
|---|---|---|
| 1 | MS conservador ≥ 20 **e** EY ≥ 12 | `COMPRA_FORTE` |
| 2 | MS base ≥ 20 **e** EY ≥ 8 | `COMPRA_MODERADA` |
| 3 | MS base < 0 | `VENDA_VALUATION` |
| 4 | posição 52s ≥ 90 **e** MS base ≤ 10 | `ALERTA_RISCO` |
| 5 | caso contrário | `MANTER` |

**Risco:** `ALTO` se MS base < 0 ou posição 52s ≥ 90; `MEDIO` se MS conservador < 0 ou amplitude ≥ 8%; senão `BAIXO`.

**Confiança (0–100):** começa em 50.
- MS conservador ≥ 20: +20; senão MS conservador ≥ 0: +10; senão, se MS base < 0: −20.
- EY ≥ 12: +15; senão EY ≥ 8: +8; senão, se EY < 6: −10.
- Posição 52s entre 25 e 75: +5; ≥ 90: −10.
- Amplitude ≥ 8%: −5.
- Resultado limitado a [0, 100].

**Insights e fatores de decisão:** mensagens geradas pelos mesmos limiares (margem, EY, P/L > 20, zona 52s, volatilidade); se nada dispara, gera `SEM_SINAL_FORTE`.

### 5.6 Estratégias existentes, não integradas — `app/core/strategies/`

| Estratégia | Compra | Venda | Dependência ausente |
|---|---|---|---|
| MeanReversion | z-score < −1,5 **e** P ≤ min52 × 1,1 | z-score > 1,5 **ou** P ≥ max52 × 0,95 | cálculo de z-score (requer histórico) |
| Momentum | P > MM20 **e** volume relativo > 1,3 | P < MM20 **e** volume relativo < 0,7 | MM20 e volume médio (requer histórico) |
| Valuation | P/L < P/L setorial × 0,8 | P/L > P/L setorial × 1,1 | fonte de P/L setorial |

---

## 6. Requisitos

### 6.1 Funcionais

| ID | Requisito | Status |
|---|---|---|
| REQ-01 | Consumir continuamente as filas `tratar-ativos` e `sqs-registrar-series-historicas`, criando-as se não existirem | IMPLEMENTADO |
| REQ-02 | Persistir cada snapshot recebido em `historico_acoes` | IMPLEMENTADO |
| REQ-03 | Calcular valuation Graham em 3 cenários e gravar o cenário base em `insight_acao` | IMPLEMENTADO |
| REQ-04 | Gerar recomendação, risco, confiança, insights e fatores de decisão conforme a seção 5 | IMPLEMENTADO |
| REQ-05 | Retornar `SEM_DADOS` quando os fundamentos forem inválidos | IMPLEMENTADO |
| REQ-06 | Fazer upsert idempotente de candles diários em `serie_historica` | IMPLEMENTADO (não commitado) |
| REQ-07 | Usar a série histórica (MM20, z-score, volume relativo) na recomendação | PARCIAL: calculado e gravado como sinal técnico (`TASK-30`, `TASK-31`); combinação com a recomendação depende de medição |
| REQ-08 | Ajustar o valuation pela taxa livre de risco brasileira | PLANEJADO (`TASK-20`) |
| REQ-09 | Incluir aviso (disclaimer) de caráter não-recomendatório no payload | PLANEJADO (`TASK-23`) |

Critérios de aceite de referência (devem virar testes):

- **REQ-03** — *Dado* `P=10` e `LPA=2`, *quando* o insight é gerado, *então* o cenário base tem `preco_justo = 29,0` (2 × 14,5) e `margem_seguranca_percent ≈ 65,5172`.
- **REQ-05** — *Dado* `earningsPerShare = -1`, *quando* o insight é gerado, *então* `recomendacao = "SEM_DADOS"` e `preco_justo_graham = null`.
- **REQ-06** — *Dado* dois payloads com o mesmo `(simbolo, data, intervalo)` e fechamentos diferentes, *quando* ambos são processados, *então* existe uma única linha, com o fechamento do segundo.

### 6.2 Não funcionais

| ID | Requisito | Status |
|---|---|---|
| NFR-01 | **Atomicidade:** todas as escritas de uma mensagem ficam em uma única transação | ATENDIDO (2026-09-26) |
| NFR-02 | **Idempotência:** reprocessar a mesma mensagem não gera duplicatas | ATENDIDO por `dedup_key` e índices únicos (2026-09-26) |
| NFR-03 | **Resiliência:** mensagens que falham repetidamente vão para uma DLQ após N tentativas | ATENDIDO na infraestrutura (2026-09-26) |
| NFR-04 | **Observabilidade:** logs estruturados em JSON, nível configurável, sem duplicação | NÃO ATENDIDO (`ISS-08`) |
| NFR-05 | **Segurança:** nenhum segredo ou ambiente virtual dentro da imagem; container sem root | NÃO ATENDIDO (`ISS-04`) |
| NFR-06 | **Testabilidade:** `app/core/analysis` com cobertura ≥ 90%; suíte verde no CI | PARCIAL — suíte verde (`ISS-03` concluído), `valuation`/`recommendation`/`technical_series` testados; % de cobertura não medido; CI ainda não roda pytest (`ISS-05`) |
| NFR-07 | **Configuração:** toda configuração vem de `Settings` (fonte única) | PARCIAL (`ISS-10`) |
| NFR-08 | **Pureza do domínio:** `app/core/analysis` sem I/O, determinístico | ATENDIDO |

---

## 7. Problemas identificados

Severidade: **Crítico** (perda/corrupção de dados ou segurança), **Alto**, **Médio**, **Baixo**.

### 7.1 Técnicos

| ID | Sev. | Problema | Evidência | Impacto | Correção sugerida | Status |
|---|---|---|---|---|---|---|
| ISS-01 | Crítico | Repositórios faziam `commit()` interno, anulando a transação do processor | Repositórios agora usam `flush`; `CoreProcessor` é o único dono do commit | Evita persistência parcial | Coberto por teste da unidade de trabalho | CONCLUIDO (2026-09-26) |
| ISS-02 | Alto | Fila de ativos sem idempotência (SQS entrega *at-least-once*) | `dedup_key` propagada pelo produtor ou calculada de forma determinística no consumidor | Evita duplicatas em reentrega | Índices únicos + consulta idempotente | CONCLUIDO (2026-09-26) |
| ISS-03 | Alto | ~~Suíte de testes quebrada e sem cobertura do domínio atual~~ | Testes legados (`test_trading_service.py` etc.) já removidos; `pytest tests -q` roda limpo | ~~Falha na coleta do pytest~~ | `app/core/analysis/valuation.py` e `recommendation.py` ganharam teste (`tests/test_valuation.py`, `tests/test_recommendation.py`, 2026-09-27) — `historical_series`/`technical_series` já tinham (`test_technical_series_analyzer.py`). Cobertura de `%` não medida (falta rodar `pytest --cov`) | CONCLUIDO (2026-09-27, verificado ao vivo: `pytest tests/ -q` → 74 passed) |
| ISS-04 | Crítico | Sem `.dockerignore`; `COPY . .` leva `.env.local`, `.venv`, `venv-local`, `.git`, `.idea` para a imagem pública; roda como root | `Dockerfile:5` | Vazamento de credenciais no Docker Hub; imagem grande | `.dockerignore`, build multi-stage, `USER` não-root | ABERTO |
| ISS-05 | Alto | CI publica a imagem (inclusive `latest`) sem rodar testes/lint | `.github/workflows/02-docker-build-push.yml:40,46` | Imagem quebrada em produção | Job `test` (pytest + ruff) como pré-requisito; `latest` só a partir de `main`/tag | ABERTO |
| ISS-06 | Alto | Erros não-de-dados causam retry infinito; sem DLQ | `app/core/core_processor.py:103` | Mensagem venenosa consome recursos para sempre e polui logs | Redrive policy com DLQ (`maxReceiveCount`), ou checar `ApproximateReceiveCount` | ABERTO |
| ISS-07 | Alto | Worker não cria nem migra o schema | não há `create_all`/Alembic no projeto. Hoje o schema vem de `infra-b3-ecossytem/mysql-init/1 - schema.sql` (só roda com volume vazio) e o Hibernate do gestor (`ddl-auto=update`) também mexe em `insight_acao` | Em ambientes com volume antigo, `serie_historica` não existe → mensagens da fila de série em retry infinito | Ver `infra#INT-04`, `infra#ISS-03`, `infra#DEC-01`; adotar Alembic se este serviço for o dono | ABERTO |
| ISS-14 | Médio | Sem endpoint de métricas/saúde, embora o compose exponha a porta 8080 e o Prometheus faça scrape nela; logs só em stdout (fora do ELK) | `infra-b3-ecossytem/docker-compose.yml`, `prometheus.yml` | Worker invisível na observabilidade | `prometheus_client` em :8080 (mensagens processadas/descartadas, latência, recomendações por tipo) + logs JSON (ver `infra#INT-06`) | ABERTO |
| ISS-08 | Médio | Logger duplica handlers a cada chamada; `LOG_LEVEL` ignorado; JSON logger não usado | `app/config/config_logger.py:5,9`; chamado em `main.py:7` e `repository_history.py:5` | Linhas de log duplicadas; sem controle de nível | Configuração única e idempotente, `python-json-logger`, nível vindo de `Settings` | ABERTO |
| ISS-09 | Médio | Novo cliente boto3 criado a cada chamada SQS | `app/config/aws_config.py:17` | Overhead de CPU/conexões | Criar o cliente uma vez e reutilizá-lo | ABERTO |
| ISS-10 | Médio | Retry do banco lê o env direto, duplicando `Settings` | `app/config/database_config.py:12-13` | Duas fontes de verdade | Usar `Settings().retry_attempts/retry_delay` | ABERTO |
| ISS-11 | Baixo | Código morto/inconsistente: `@dataclass` com `__init__` manual; `datetime.utcnow` (deprecado); exceções em `app/exceptions` não usadas; pydantic e requests declarados sem uso. DynamoDB já removido (ver DEC-04) | `app/external/database/insight_repository.py:7`, entidades, `requirements.txt` | Ruído, confusão para novos devs/agentes | Limpeza; usar `datetime.now(timezone.utc)` | ABERTO |
| ISS-12 | Baixo | README com texto residual de chatbot e informação incorreta (diz que as estratégias rodam) | `README.md:50,149` | Documentação enganosa | Reescrever o README apontando para esta spec | ABERTO |
| ISS-13 | Médio | Feature de série histórica não commitada (4 arquivos novos, 4 modificados) | `git status` | Risco de perda de trabalho | Commitar em branch `feature/*` com testes | ABERTO |

### 7.2 Financeiros (visão de analista)

| ID | Sev. | Problema | Impacto | Correção sugerida | Status |
|---|---|---|---|---|---|
| ISS-F1 | Alto | ~~Graham sem ajuste de juros~~ | `app/core/analysis/valuation.py` (`GrahamValuation`, `fator_de_juros`) | ~~Viés estrutural para `COMPRA_*`~~ | `Y` = Selic meta vigente (`indice_macro`, ver `DEC-02`); cenário sem ajuste preservado só como referência em `cenarios_graham_sem_ajuste_juros`, fora da recomendação. Testado em `tests/test_valuation.py` | CONCLUIDO (2026-09-27) |
| ISS-F2 | Alto | ~~LPA dos últimos 12 meses sem normalização~~ | `app/core/analysis/valuation.py` (`normalizar_lpa`, `graham_number`) | ~~Cíclica no pico do lucro saía `COMPRA_FORTE`~~ | LPA = mínimo entre o atual e a média de 3–5 anos entregues à CVM; Graham Number como segunda trava de `COMPRA_FORTE` (rebaixa para `COMPRA_MODERADA` se o preço passa do número). Testado em `tests/test_valuation.py` | CONCLUIDO (2026-09-27) |
| ISS-F3 | Médio | ~~`VENDA_VALUATION` sempre que MS base < 0~~ | `app/core/analysis/limiares.py` (`margem_venda`), `app/core/analysis/recommendation.py` | ~~Quase toda empresa de crescimento virava "venda"~~ | Faixa neutra: `margem_venda` (−15% na primeira versão; −100% após a calibração, `DEC-07`) < MS base < 0 → `MANTER`; só abaixo de −15% é `VENDA_VALUATION`. Múltiplo-base (`multiplo_base`, 8,5) já é parâmetro em `Limiares`, não constante. Testado em `tests/test_recommendation.py` | CONCLUIDO (2026-09-27) |
| ISS-F4 | Médio | Limiares (20%, 12%, 85/90) e score de confiança são heurísticos, sem backtest ou calibração; sem noção de setor | Confiança sem significado estatístico | Backtest (`TASK-40`); limiares configuráveis e versionados | PARCIAL: limiares versionados em `limiares.py` e calibrados por backtest (`TASK-41`, `DEC-07`); score de confiança e setor seguem heurísticos |
| ISS-F5 | Médio | A recomendação principal (valuation) usa um único snapshot; a série histórica entra só como sinal técnico separado | Momentum e reversão à média já são calculados sobre a série (≥ 20 candles) e gravados no insight e no diário, mas não pesam na recomendação; o acerto deles ainda não foi medido | Medir os sinais técnicos no diário/backtest antes de combiná-los à recomendação | PARCIAL (TASK-30, TASK-31 concluídas) |
| ISS-F6 | Médio | Rótulos "COMPRA/VENDA" podem configurar recomendação de investimento (atividade regulada pela CVM, Res. 20/2021) | Risco regulatório/reputacional se exposto a usuários finais | Rotular como "sinal quantitativo", incluir disclaimer no payload, revisar com jurídico | ABERTO |
| ISS-F7 | Alto | ~~Retorno do backtest/diário usa preço bruto (COTAHIST), sem proventos~~ | `app/validacao/avaliador.py` (`avaliar`, `_proventos_no_periodo`), `app/validacao/proventos.py` | ~~Pagadora de dividendo parecia sistematicamente pior do que era~~ | Retorno passa a somar proventos com data-com na janela [entrada, saída) do sinal, lidos de `provento_distribuido` (gestor-ativos-brutos, endpoint da B3). Cobertura só a partir de 27/09/2026 (fonte só devolve ~12 meses por consulta); sinais mais antigos ficam sem ajuste. Testado em `tests/test_avaliador.py` (`test_provento_na_janela_soma_ao_retorno` e correlatos) | CONCLUIDO (2026-09-27), cobertura PARCIAL (ver TASK-46) |

---

## 8. Roadmap e tarefas

Cada tarefa referencia os itens que resolve. Ordem sugerida: fases 0 → 4. Dentro de cada fase, as tarefas são independentes, salvo indicação em "Depende de".

### Fase 0 — Estabilizar

| ID | Tarefa | Resolve | Arquivos-alvo | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|---|
| TASK-01 | Commitar a feature de série histórica em branch `feature/serie-historica` | ISS-13 | `app/core/mapper/historical_series.py`, `app/core/service/serie_historica_service.py`, entidade, repositório | `git status` limpo; PR aberto | — | ABERTO |
| TASK-02 | Criar `.dockerignore`, build multi-stage e usuário não-root | ISS-04 | `Dockerfile`, `.dockerignore` | `docker run --rm <img> ls -a /app` não lista `.env*`, `.venv`, `venv-local`, `.git`; `whoami` ≠ root | — | ABERTO |
| TASK-03 | Remover/reescrever os testes legados | ISS-03 | `tests/test_trading_service.py`, `tests/test_aggregator_service.py`, `tests/test_e2e_flow.py` | `pytest tests -q` coleta sem erros | — | ABERTO |
| TASK-04 | Testes unitários do domínio (`valuation`, `technical_context`, `recommendation`, `insight_payload`, `historical_series`) com os critérios da seção 6.1 | ISS-03, NFR-06 | `tests/analysis/*` | Cobertura de `app/core/analysis` ≥ 90% | TASK-03 | ABERTO |
| TASK-05 | Job de CI com pytest + lint antes do build; `latest` apenas em `main` | ISS-05 | `.github/workflows/*` | PR com teste vermelho não publica imagem | TASK-03 | ABERTO |
| TASK-06 | Reescrever o README (remover resíduos, apontar para esta spec) | ISS-12 | `README.md` | Nenhuma afirmação contradiz esta spec | — | ABERTO |

### Fase 1 — Confiabilidade

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-10 | Tirar os `commit()` dos repositórios; unidade de trabalho única no `CoreProcessor` | ISS-01, NFR-01 | *Dado* uma falha forçada em `salvar_insight`, *quando* a mensagem é processada, *então* nenhuma linha nova existe em `historico_acoes` | TASK-04 | CONCLUIDO (2026-09-26) |
| TASK-11 | Chave de idempotência para snapshots e insights | ISS-02, NFR-02 | Processar a mesma mensagem 2× gera 1 linha em cada tabela | TASK-10, DEC-01 | CONCLUIDO (2026-09-26) |
| TASK-12 | DLQ com `maxReceiveCount` configurável | ISS-06, NFR-03 | Mensagem que sempre falha chega à DLQ após N tentativas | — | CONCLUIDO na infra (2026-09-26) |
| TASK-13 | Logger único, JSON, nível via `Settings.log_level` | ISS-08, NFR-04 | Cada evento aparece uma vez; `LOG_LEVEL=DEBUG` habilita logs de debug | — | ABERTO |
| TASK-14 | Reutilizar o cliente SQS; retry do banco via `Settings` | ISS-09, ISS-10, NFR-07 | Uma instância de cliente por processo; nenhum `os.getenv` fora de `settings.py` | — | ABERTO |
| TASK-15 | Migrations com Alembic (ou `create_all` controlado por flag) | ISS-07 | Banco vazio + `alembic upgrade head` cria as 3 tabelas usadas | DEC-01 | ABERTO |
| TASK-16 | Limpeza de código morto e dependências não usadas | ISS-11 | `requirements.txt` só com dependências importadas | — | ABERTO |

### Fase 2 — Qualidade financeira

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-20 | Graham com ajuste `× 4,4 / Y`, com `Y` configurável | ISS-F1, REQ-08 | *Dado* `LPA=2`, `g=3`, `Y=4,4`, *então* `V=29`; *dado* `Y=8,8`, *então* `V=14,5` — ambos os casos em `tests/test_valuation.py::test_criterio_aceite_task20_*` | TASK-04, DEC-02 | CONCLUIDO (2026-09-27) |
| TASK-21 | Aceitar VPA e calcular o Graham Number como métrica complementar | ISS-F2 | Campo `graham_number` no payload quando houver VPA > 0 | VPA lido de `indicador_fundamentalista` (CVM, pela data de entrega), não do produtor Java | CONCLUIDO (2026-09-27): `valuation.graham_number`, trava de `COMPRA_FORTE` em `recommendation.py` |
| TASK-22 | Faixa neutra para `VENDA_VALUATION`; limiares em configuração versionada | ISS-F3, ISS-F4 | Limiares lidos de config; testes cobrem as bordas | TASK-04 | CONCLUIDO (2026-09-27): `app/core/analysis/limiares.py`; bordas em `tests/test_recommendation.py` |
| TASK-23 | `versao_payload = "3.0"` com campo `aviso_legal` e rótulos revisados | ISS-F6, REQ-09 | Todo insight contém `aviso_legal`; consumidores informados | DEC-05 | ABERTO |

### Fase 3 — Análise com histórico

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-30 | Serviço de indicadores sobre `serie_historica`: MM20, volume médio 20d, z-score 52s | ISS-F5, REQ-07 | Funções puras testadas com séries sintéticas | TASK-01, TASK-04 | CONCLUIDO (2026-09-26): `app/core/analysis/technical_series.py`, com preço ajustado por proventos; testes em `tests/test_technical_series_analyzer.py` |
| TASK-31 | Conectar `MomentumStrategy` e `MeanReversionStrategy` como sinais técnicos | ISS-F5 | Sinais preenchidos quando houver ≥ 20 candles | TASK-30 | CONCLUIDO (2026-09-26): `SerieTecnicaService` grava `sinal_momentum`/`sinal_reversao` em `detalhes_json.contexto_tecnico_serie` (nome real do campo, não `sinais_tecnicos`) e o diário os registra; eles NÃO alteram a recomendação principal, que segue a de valuation |
| TASK-32 | Fonte de P/L setorial para `ValuationStrategy` (ou remover a estratégia) | ISS-F4 | Decisão registrada em DEC; estratégia ativa ou removida | DEC-06 | ABERTO |

### Fase 4 — Validação

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-40 | Backtest walk-forward sem viés de futuro: snapshot reconstruído com COTAHIST e LPA TTM **com `DT_RECEB` ≤ t** (arquivo-índice do DFP/ITR; defasagem mediana de 79 dias entre fim do exercício e entrega), amostragem mensal, teste congelado de 2023 em diante, contra a média da carteira e o CDI | ISS-F4 | Relatório por classe × horizonte (21/63/126 pregões) com n, acerto vs taxa-base, excesso e IC por bootstrap; mesmos parâmetros → mesmos números | TASK-42, TASK-43; ETL: `DT_RECEB`, COTAHIST 2016+ | ABERTO |
| TASK-41 | Recalibrar limiares com base no backtest | ISS-F4 | Nova versão de limiares registrada em DEC (e `VERSAO_REGRA` incrementada) | TASK-40 | CONCLUIDO (2026-09-27): `python -m app.validacao.calibracao`; `margem_venda` −15 → −100, `VERSAO_REGRA` 2026.09.27-2, números em `DEC-07`. Score de confiança não recalibrado (fica para depois do diário ter amostra) |
| TASK-42 | Motor de avaliação único para backtest e diário (`app/validacao/avaliador.py`): entrada na abertura do pregão seguinte, saída no fechamento do h-ésimo pregão, custo 0,10% ida e volta, excesso sobre a média da carteira (V5) e sobre o CDI, acerto só para recomendação com direção, janela com salto ≥ 40% marcada como suspeita | ISS-F4 | `tests/test_avaliador.py` (14 casos) | — | CONCLUIDO (2026-09-26) |
| TASK-43 | `VERSAO_REGRA` (`app/core/analysis/versao_regra.py`) gravada em todo `detalhes_json`; incrementar a cada mudança que altere a saída | ISS-F4 | Teste fixa a versão atual | — | CONCLUIDO (2026-09-26) |
| TASK-44 | Diário de sinais (`python -m app.validacao.diario registrar|avaliar`): um sinal por ativo por pregão por versão, só inclusão (`infra#CTR-11`) | ISS-F4 | `tests/test_diario.py` (16 casos); registrar duas vezes não duplica; horizonte só é avaliado quando vence | TASK-42, TASK-43 | CONCLUIDO (2026-09-26) |
| TASK-45 | Agendar `registrar` e `avaliar` todo dia útil após o fechamento (Agendador de Tarefas do Windows chamando `docker compose run`) | ISS-F4 | Um registro por pregão sem intervenção manual | TASK-44 | ABERTO |
| TASK-46 | Backfill histórico de proventos (2017+) para o backtest todo, não só a partir de 27/09/2026 | ISS-F7 | Fonte alternativa à B3 ao vivo (que só cobre ~12 meses) identificada e carregada; retorno do backtest inteiro passa a incluir proventos, não só os sinais recentes | TASK-40; `provento_distribuido` (gestor) | ABERTO |
| TASK-47 | `app/validacao/proventos.py`: distinguir provento por classe de ação (ON/PN) via ISIN, em vez de usar o maior valor entre classes | ISS-F7 | Teste com evento de valores diferentes por classe usa o valor da classe correta, não o maior | TASK-46 | ABERTO |

---

## 9. Decisões

| ID | Pergunta | Opções | Status | Decisão / data |
|---|---|---|---|---|
| DEC-01 | Quem é dono do schema MySQL? | (a) app Java; (b) este worker via Alembic; (c) repositório de migrations compartilhado | ABERTO — decidido no nível do ecossistema (`infra#DEC-01`) | — |
| DEC-02 | Qual taxa usar como `Y` no Graham ajustado? | NTN-B longa (real) / Selic / CDI / valor fixo configurável | RESOLVIDO (2026-09-27): **Selic meta vigente** (SGS 432, `indice_macro.codigo_serie = 'SELIC'`, % a.a.), a do dia da análise; no backtest, a vigente na data do sinal. Motivos: é a única taxa livre de risco que o ecossistema já coleta (o gestor a grava e o painel a mostra em Índices); NTN-B longa exigiria ingerir os preços do Tesouro Direto e fica como evolução. Sem taxa disponível, o insight sai `SEM_DADOS` em vez de cair na fórmula sem ajuste (misturaria duas regras sob a mesma versão). A fórmula de 1962 (`Y = 4,4`, fator 1) continua calculada em `cenarios_graham_sem_ajuste_juros`, **só como referência histórica** — não entra na recomendação. Consequência conhecida: `Y` nominal com `g` real (0/3/5) é conservador; tratado nas sessões de ISS-F2/F3 | — |
| DEC-03 | Política de retenção de `historico_acoes` | manter tudo / agregar por dia / expurgar após N dias | ABERTO | — |
| DEC-04 | DynamoDB: implementar ou remover do projeto? | implementar / remover | RESOLVIDO: removido (config morta em `settings.py`/`aws_config.py`, nunca usada) | — |
| DEC-05 | Nomenclatura das recomendações | manter COMPRA/VENDA / "sinal quantitativo" (ex.: `SINAL_POSITIVO_FORTE`) | ABERTO | — |
| DEC-06 | Fonte de P/L setorial | API externa / tabela manual / calcular a partir de `ativos` | ABERTO | — |
| DEC-07 | Limiares da v1 depois do ajuste de juros (TASK-41) | manter os da fórmula sem juros / calibrar por backtest | RESOLVIDO (2026-09-27): **calibrados**. Protocolo (`app/validacao/calibracao.py`): grade de 1.440 combinações de `multiplo_base`, margens e earnings yield, avaliada só na calibração (sinais até 2022-12-31, horizonte 63 pregões); objetivo = excesso médio sobre a carteira das compras menos o das vendas, com ≥ 60 janelas em cada lado e venda em no máximo 50% das janelas (sem esta trava a primeira passada escolheu 92% de venda no teste). O teste (2023+) foi olhado uma vez, como veredito. Adotado: `margem_venda = −100`; demais limiares mantidos (empatavam no topo). Medido no teste, 63 pregões: separação compra × venda **3,4 p.p.** (v1 com −15: 2,9; v1 antiga sem juros: 2,4); compras 24 janelas, acerto 58% (taxa-base 52%), +3,6% sobre a carteira; vendas 69% das janelas, acerto 51% (≈ taxa-base: sem vantagem). **Não generalizou**: a fração de vendas (49% na calibração, 69% no teste) depende do regime de juros, porque `Y` é nominal e `g` é real — com Selic de 2–6% (calibração) o fator 4,4/Y é ~1, com 11–15% (teste) é ~0,3. Próximo passo: crescimento nominal (`g` + IPCA), como a v2 já faz | — |

---

## 10. Glossário

| Termo | Definição |
|---|---|
| LPA (EPS) | Lucro por ação dos últimos 12 meses |
| VPA (BVPS) | Valor patrimonial por ação |
| P/L (P/E) | Preço ÷ LPA |
| Earnings yield (EY) | LPA ÷ Preço; o "rendimento de lucro", inverso do P/L |
| Preço justo de Graham | `LPA × (8,5 + 2g)`, opcionalmente `× 4,4 / Y` |
| Graham Number | `√(22,5 × LPA × VPA)` |
| Margem de segurança | (Valor justo − Preço) ÷ Valor justo |
| Range de 52 semanas | Intervalo entre a mínima e a máxima do último ano |
| Candle | Registro OHLCV (abertura, máxima, mínima, fechamento, volume) de um período |
| MM20 | Média móvel simples de 20 pregões |
| z-score | (Preço − média) ÷ desvio-padrão |
| DLQ | Dead-letter queue: fila que recebe mensagens que falharam repetidamente |
| Idempotência | Processar a mesma mensagem N vezes tem o mesmo efeito que processá-la uma vez |
| At-least-once | Garantia do SQS: toda mensagem é entregue ao menos uma vez, possivelmente mais |

---

## 11. Comandos de verificação

```bash
# ambiente
python -m venv .venv
.venv/Scripts/activate            # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

# testes
pytest tests -v

# execução local (exige LocalStack em :4566 e MySQL em :3305)
ENVIRONMENT=local python main.py

# imagem
docker build -t gerar-insights:dev .

# mensagem de teste
awslocal sqs send-message \
  --queue-url http://localhost:4566/000000000000/tratar-ativos \
  --message-body '{"symbol":"TEST3","regularMarketPrice":10,"earningsPerShare":2,"priceEarnings":5,"fiftyTwoWeekLow":8,"fiftyTwoWeekHigh":14}'
```

Resultado esperado da mensagem de teste (regras atuais): cenário base `preco_justo = 29`, `margem ≈ 65,52%`, `EY = 20%`, MS conservador = 41,18% → `COMPRA_FORTE`.
