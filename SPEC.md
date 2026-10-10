# SPEC — gerar-insights (Motor Financeiro)

| Campo | Valor |
|---|---|
| Versão da spec | 1.0.0 |
| Data | 2026-09-27 |
| Status | IMPLEMENTADO |
| Specs relacionadas | `infra-b3-ecossytem/SPEC.md` (ecossistema, Docker, contratos `CTR-` e problemas de integração `INT-`) · `gestor-ativos-brutos/SPEC.md` (produtor SQS e leitor de `insight_acao`) |
| Público | Desenvolvedores humanos e agentes de IA (Codex, ChatGPT, Claude ou outros) |

---

## Corte e estados comuns

Data de corte: **2026-09-27** (America/Sao_Paulo). `PLANEJADO`: ainda não executado; `EM ANDAMENTO`: entrega parcial; `IMPLEMENTADO`: código ou decisão presente, sem confirmação integral nesta revisão; `VERIFICADO`: aceite demonstrado por verificação registrada; `BLOQUEADO`: dependência impeditiva identificada. Datas anteriores permanecem como histórico. Resolver um problema significa implementar sua correção; funcionalidades descontinuadas mantêm o ID e registram a resolução. Evidências antigas não são nova validação operacional.

## 1. Como usar este arquivo (protocolo para agentes)

Este é o **documento-fonte** do projeto, no modelo Spec Driven Development (SDD). Código, testes e planos derivam daqui.

**Fluxo obrigatório:** `Spec → Plano → Tarefas → Implementação → Verificação → Atualizar Spec`.

Regras:

1. Antes de alterar código, leia as seções 2 a 7. Toda alteração deve estar ligada a um ID (`REQ-`, `NFR-`, `ISS-` ou `TASK-`).
2. **IDs são estáveis.** Nunca renumere nem apague um ID; para descontinuar, mude o status para `IMPLEMENTADO (descontinuado)` com justificativa.
Estados válidos de requisitos, tarefas, problemas e decisões: `PLANEJADO`, `EM ANDAMENTO`, `IMPLEMENTADO`, `VERIFICADO`, `BLOQUEADO`. Descontinuação é uma resolução descrita, não um estado adicional.
4. Ao concluir uma `TASK-`, atualize o status, registre a data e cite o commit/PR na coluna "Notas".
5. Decisões de design ou de negócio viram uma entrada `DEC-` (seção 9). Não tome decisões marcadas como abertas sem registrar a escolha.
6. Não invente requisitos: se algo não está aqui, proponha um novo item (`REQ-`/`TASK-`) com status `PLANEJADO`/`PLANEJADO` em vez de implementá-lo direto.
7. Critérios de aceite usam o formato **Dado / Quando / Então** e devem virar testes automatizados sempre que possível.
8. Mudanças em regras financeiras (seção 5) exigem incrementar `versao_payload` e atualizar esta spec no mesmo PR.

---

## 1A. Coordenação entre agentes (estado em 2026-10-04)

**Hub:** `infra-b3-ecossytem/SPEC.md` seção 1A — fila única, contratos, handoff e diário. Leia antes de codar; atualize lá ao pegar e ao fechar tarefa. Em conflito com seções antigas abaixo, vale o hub e esta seção.

- **Dono neste repo:** worker (consome SQS, grava `insight_acao`), CLIs `app.insights_diarios` (`--recuperar`), `app.validacao.diario`, `app.validacao.backtest`, fatores/eventos do Plano LAC (LAC-INS-1..9).
- **Mensageria hoje:** valida JSON Schema antes da transação; inbox `evento_processado` (V14); ACK só após commit; payload inválido é **mantido para a DLQ** (§3.4 antiga que diz descartar está obsoleta). Contrato de `insight.schema.json` vem de `infra/contracts` (sincronizado por script).
- **Conclusão de pesquisa:** backtest sem vantagem distinguível (DEC-07/08/09). Nada aqui promove regra a "recomendada" sem os critérios de LAC-INS-9; manter aviso de regra experimental.
- **Fila local:** LAC-INS-1..9 `IMPLEMENTADO` (8e9e159) — falta validar com dados reais após backfill (LAC-INFRA-3) e criar a rotina mensal (LAC-INFRA-4). TASK-45 (agendar `--recuperar`) está feita pela rotina da manhã da infra.
- **Arquivos não commitados de outra sessão (contratos/inbox):** `app/contracts/`, `app/core/event_contracts.py`, `app/external/database/evento_repository.py`, `insight_payload.py`, `core_processor.py`, `financial_analyzer_service.py`, `requirements.txt` — não editar nem commitar sem o dono.

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
| `tests/` | Pytest — suíte estabilizada; domínio financeiro coberto por testes unitários (ver `ISS-03`) |
| `.github/workflows/` | CI: auto-PR `feature*` → `develop`; push em `develop` → build/push Docker Hub |

### 3.3 Stack
Python 3.11 (imagem `python:3.11-slim`), boto3/botocore, SQLAlchemy ≥ 2, PyMySQL, python-dotenv, python-json-logger, prometheus-client.

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
| `LOG_LEVEL` | `INFO` | nível do logger JSON do worker |
| `METRICS_ENABLED` / `METRICS_PORT` | `true` / `8080` | idem |
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
| Valuation | INATIVA | INATIVA | `DEC-06`: sem fonte point-in-time confiável de P/L setorial; `ValuationStrategy` não altera recomendação |

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
| REQ-06 | Fazer upsert idempotente de candles diários em `serie_historica` | IMPLEMENTADO (registrado no código) |
| REQ-07 | Usar a série histórica (MM20, z-score, volume relativo) na recomendação | IMPLEMENTADO COMO SINAL SEPARADO: calculado e gravado como contexto técnico (`TASK-30`, `TASK-31`) e medido no backtest como regras próprias (`TASK-52`). Por decisão de produto/validação, ainda não altera a recomendação principal de valuation |
| REQ-08 | Ajustar o valuation pela taxa livre de risco brasileira | IMPLEMENTADO — Selic vigente, crescimento nominal, `DEC-08` |
| REQ-09 | Incluir aviso de caráter não-recomendatório no payload | IMPLEMENTADO — payload 3.0 exige `aviso_legal`; `resumo.sinal_quantitativo` usa os rótulos de `DEC-05` e o alias `recomendacao` é mantido durante a transição |

Critérios de aceite de referência (devem virar testes):

- **REQ-03** — *Dado* `P=10` e `LPA=2`, *quando* o insight é gerado, *então* o cenário base tem `preco_justo = 29,0` (2 × 14,5) e `margem_seguranca_percent ≈ 65,5172`.
- **REQ-05** — *Dado* `earningsPerShare = -1`, *quando* o insight é gerado, *então* `recomendacao = "SEM_DADOS"` e `preco_justo_graham = null`.
- **REQ-06** — *Dado* dois payloads com o mesmo `(simbolo, data, intervalo)` e fechamentos diferentes, *quando* ambos são processados, *então* existe uma única linha, com o fechamento do segundo.

### 6.2 Não funcionais

| ID | Requisito | Status |
|---|---|---|
| NFR-01 | **Atomicidade:** todas as escritas de uma mensagem ficam em uma única transação | IMPLEMENTADO (2026-09-26) |
| NFR-02 | **Idempotência:** reprocessar a mesma mensagem não gera duplicatas | IMPLEMENTADO por `dedup_key` e índices únicos (2026-09-26) |
| NFR-03 | **Resiliência:** mensagens que falham repetidamente vão para uma DLQ após N tentativas | IMPLEMENTADO na infraestrutura (2026-09-26) |
| NFR-04 | **Observabilidade:** logs estruturados em JSON, nível configurável, sem duplicação, métricas HTTP para Prometheus | IMPLEMENTADO (2026-10-08: `TASK-13` + `ISS-14`) |
| NFR-05 | **Segurança:** nenhum segredo ou ambiente virtual dentro da imagem; container sem root | IMPLEMENTADO (2026-10-07, `ISS-04`/`TASK-02`) |
| NFR-06 | **Testabilidade:** `app/core/analysis` com cobertura ≥ 90%; suíte verde no CI | IMPLEMENTADO — cobertura de `app/core/analysis` em 100% na validação de 2026-10-08; CI executa ruff e pytest com cobertura (`ISS-03`, `TASK-05`) |
| NFR-07 | **Configuração:** toda configuração vem de `Settings` (fonte única) | EM ANDAMENTO (`ISS-10`) |
| NFR-08 | **Pureza do domínio:** `app/core/analysis` sem I/O, determinístico | IMPLEMENTADO |

---

## 7. Problemas identificados

Severidade: **Crítico** (perda/corrupção de dados ou segurança), **Alto**, **Médio**, **Baixo**.

### 7.1 Técnicos

| ID | Sev. | Problema | Evidência | Impacto | Correção sugerida | Status |
|---|---|---|---|---|---|---|
| ISS-01 | Crítico | Repositórios faziam `commit()` interno, anulando a transação do processor | Repositórios agora usam `flush`; `CoreProcessor` é o único dono do commit | Evita persistência parcial | Coberto por teste da unidade de trabalho | IMPLEMENTADO (2026-09-26) |
| ISS-02 | Alto | Fila de ativos sem idempotência (SQS entrega *at-least-once*) | `dedup_key` propagada pelo produtor ou calculada de forma determinística no consumidor | Evita duplicatas em reentrega | Índices únicos + consulta idempotente | IMPLEMENTADO (2026-09-26) |
| ISS-03 | Alto | ~~Suíte de testes quebrada e sem cobertura do domínio atual~~ | Testes legados (`test_trading_service.py` etc.) removidos no commit `13c010e`; suíte-base coleta e executa sem erros | ~~Falha na coleta do pytest~~ | Casos unitários adicionais em `tests/analysis/` cobrem valuation, recomendação, contexto técnico, payload e séries históricas | IMPLEMENTADO (validado em 2026-10-08: suíte-base com 158 testes aprovados e 1 ignorado; `app/core/analysis` com 100% de cobertura) |
| ISS-04 | Crítico | Sem `.dockerignore`; `COPY . .` leva `.env.local`, `.venv`, `venv-local`, `.git`, `.idea` para a imagem pública; roda como root | `Dockerfile:5` | Vazamento de credenciais no Docker Hub; imagem grande | `.dockerignore`, build multi-stage, `USER` não-root | RESOLVIDO 2026-10-07 (.dockerignore, USER nao-root, env/.env.docker fora do git) |
| ISS-05 | Alto | CI publica a imagem (inclusive `latest`) sem rodar testes/lint | `.github/workflows/02-docker-build-push.yml:40,46` | Imagem quebrada em produção | Job `test` (pytest + ruff) como pré-requisito; `latest` só a partir de `main`/tag | RESOLVIDO 2026-10-07 (job test antes do build; latest so da main) |
| ISS-06 | Alto | Erros não-de-dados poderiam causar retry infinito sem DLQ | `app/core/core_processor.py:103`; infra `TASK-12` | Mensagem venenosa consumiria recursos para sempre e poluiria logs | Redrive policy com DLQ (`maxReceiveCount`) configurada na infraestrutura; worker mantém erro para SQS redirigir após tentativas | IMPLEMENTADO pela infra (2026-09-26; reconciliado em 2026-10-08) |
| ISS-07 | Alto | Worker não cria nem migra o schema | não há `create_all`/Alembic no projeto por decisão explícita: o schema é propriedade exclusiva da infraestrutura/Flyway (`DEC-01`, `TASK-15`) | Evita donos concorrentes de DDL entre worker, gestor e infra | Worker valida/usa tabelas existentes; migrations seguem em `infra-b3-ecossytem` | IMPLEMENTADO POR DECISÃO (2026-10-08: reconciliado com `DEC-01`/`TASK-15`) |
| ISS-14 | Médio | Sem endpoint de métricas/saúde, embora o compose exponha a porta 8080 e o Prometheus faça scrape nela | `app/config/observability.py`, `main.py`, `app/core/core_processor.py` | Worker invisível na observabilidade | `/health` e `/metrics` em `METRICS_PORT` (padrão 8080); métricas de mensagens por fila/resultado, latência de processamento e recomendações por tipo; logs JSON já cobertos por `TASK-13` | IMPLEMENTADO (2026-10-08) |
| ISS-08 | Médio | Logger duplicava handlers, ignorava `LOG_LEVEL` e não emitia JSON | `app/config/config_logger.py` | Linhas de log duplicadas; sem controle de nível | Configuração única e idempotente, `python-json-logger`, nível vindo de `Settings` | IMPLEMENTADO (2026-10-08: JSON + LOG_LEVEL + handler único) |
| ISS-09 | Médio | Novo cliente boto3 criado a cada chamada SQS | `app/config/aws_config.py:17` | Overhead de CPU/conexões | Criar o cliente uma vez e reutilizá-lo | RESOLVIDO 2026-10-07 (um cliente SQS por processo) |
| ISS-10 | Médio | Retry do banco lia o env direto, duplicando `Settings` | `app/config/database_config.py` | Duas fontes de verdade | Usar `Settings().retry_attempts/retry_delay` | IMPLEMENTADO (2026-10-08) |
| ISS-11 | Baixo | Código morto/inconsistente: `@dataclass` com `__init__` manual; `datetime.utcnow` (deprecado); dependências declaradas sem uso. DynamoDB já removido (ver DEC-04) | `app/external/database/insight_repository.py`, entidades, `requirements.txt` | Ruído, confusão para novos devs/agentes | Limpeza; usar `datetime.now(timezone.utc)` | IMPLEMENTADO (2026-10-08: limpeza conservadora de dataclass manual, `utcnow`, `pydantic` e `requests`) |
| ISS-12 | Baixo | ~~README com texto residual de chatbot e informação incorreta~~ | `README.md` reescrito e vinculado a esta especificação | ~~Documentação enganosa~~ | Manter detalhes normativos na `SPEC.md` e o README operacional | IMPLEMENTADO (2026-10-08) |
| ISS-13 | Médio | ~~Feature de série histórica não commitada~~ | Implementação e testes registrados no commit `13c010e`, já contido em `feature-migrate` e `develop` | ~~Risco de perda de trabalho~~ | Preservar o histórico existente; não criar branch retroativa | IMPLEMENTADO (2026-09-25) |

### 7.2 Financeiros (visão de analista)

| ID | Sev. | Problema | Impacto | Correção sugerida | Status |
|---|---|---|---|---|---|
| ISS-F1 | Alto | ~~Graham sem ajuste de juros~~ | `app/core/analysis/valuation.py` (`GrahamValuation`, `fator_de_juros`) | ~~Viés estrutural para `COMPRA_*`~~ | `Y` = Selic meta vigente (`indice_macro`, ver `DEC-02`); cenário sem ajuste preservado só como referência em `cenarios_graham_sem_ajuste_juros`, fora da recomendação. Testado em `tests/test_valuation.py` | IMPLEMENTADO (2026-09-27) |
| ISS-F2 | Alto | ~~LPA dos últimos 12 meses sem normalização~~ | `app/core/analysis/valuation.py` (`normalizar_lpa`, `graham_number`) | ~~Cíclica no pico do lucro saía `COMPRA_FORTE`~~ | LPA = mínimo entre o atual e a média de 3–5 anos entregues à CVM; Graham Number como segunda trava de `COMPRA_FORTE` (rebaixa para `COMPRA_MODERADA` se o preço passa do número). Testado em `tests/test_valuation.py` | IMPLEMENTADO (2026-09-27) |
| ISS-F3 | Médio | ~~`VENDA_VALUATION` sempre que MS base < 0~~ | `app/core/analysis/limiares.py` (`margem_venda`), `app/core/analysis/recommendation.py` | ~~Quase toda empresa de crescimento virava "venda"~~ | Faixa neutra: `margem_venda` (−15% na primeira versão; −100% após a calibração, `DEC-07`) < MS base < 0 → `MANTER`; só abaixo de −15% é `VENDA_VALUATION`. Múltiplo-base (`multiplo_base`, 8,5) já é parâmetro em `Limiares`, não constante. Testado em `tests/test_recommendation.py` | IMPLEMENTADO (2026-09-27) |
| ISS-F4 | Médio | Limiares (20%, 12%, 85/90) e score de confiança são heurísticos, sem backtest ou calibração; sem noção de setor | Confiança sem significado estatístico | Backtest (`TASK-40`); limiares configuráveis e versionados | EM ANDAMENTO: limiares versionados em `limiares.py` e calibrados por backtest (`TASK-41`, `DEC-07`); score de confiança e setor seguem heurísticos |
| ISS-F5 | Médio | A recomendação principal (valuation) usa um único snapshot; a série histórica entra só como sinal técnico separado | Momentum e reversão à média já são calculados sobre a série (≥ 20 candles), gravados no insight/diário e entram no backtest como versões próprias (`TECNICO_MOMENTUM_2026.10.07-1`, `TECNICO_REVERSAO_2026.10.07-1`), sem alterar a recomendação principal | Executar placar real amplo e registrar DEC antes de qualquer combinação com valuation | IMPLEMENTADO NO CÓDIGO / PENDENTE DE EXECUÇÃO REAL (2026-10-08: escopo técnico fechado por `TASK-30`, `TASK-31`, `TASK-52`) |
| ISS-F6 | Médio | Rótulos "COMPRA/VENDA" podem configurar recomendação de investimento (atividade regulada pela CVM, Res. 20/2021) | Risco regulatório/reputacional se exposto a usuários finais | Payload 3.0 usa `SINAL_POSITIVO_FORTE`, `SINAL_POSITIVO`, `SEM_MARGEM`, `ALERTA_RISCO`, `NEUTRO` e `SEM_DADOS`, sempre com `aviso_legal`; gestor e painel aceitam v2 e v3. Revisão jurídica humana continua recomendada | MITIGADO TECNICAMENTE (2026-10-07) |
| ISS-F7 | Alto | ~~Retorno do backtest/diário usa preço bruto (COTAHIST), sem proventos~~ | `app/validacao/avaliador.py` (`avaliar`, `_proventos_no_periodo`), `app/validacao/proventos.py`, `app/fatores/fonte_proventos.py` | ~~Pagadora de dividendo parecia sistematicamente pior do que era~~ | Retorno passa a somar proventos com data-com na janela [entrada, saída) do sinal. No backtest, `FonteProventos` combina `provento_distribuido` (B3) com `provento_contabil` (DVA/CVM) para cobrir histórico; no diário, `provento_distribuido` distingue classe por ISIN quando `cvm_ticker.isin` existe, com fallback por emissor em bases antigas. Testado em `tests/test_avaliador.py` e `tests/test_fatores_lac.py` | IMPLEMENTADO (2026-10-07) |

---

## 8. Roadmap e tarefas

Cada tarefa referencia os itens que resolve. Ordem sugerida: fases 0 → 4. Dentro de cada fase, as tarefas são independentes, salvo indicação em "Depende de".

### Fase 0 — Estabilizar

| ID | Tarefa | Resolve | Arquivos-alvo | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|---|
| TASK-01 | Commitar a feature de série histórica em branch `feature/serie-historica` | ISS-13 | `app/core/mapper/historical_series.py`, `app/core/service/serie_historica_service.py`, entidade, repositório | Feature versionada e integrada | — | IMPLEMENTADO (2026-09-25): commit `13c010e`, presente em `feature-migrate` e `develop`; branch/PR retroativos dispensados |
| TASK-02 | Criar `.dockerignore`, build multi-stage e usuário não-root | ISS-04 | `Dockerfile`, `.dockerignore` | `docker run --rm <img> ls -a /app` não lista `.env*`, `.venv`, `venv-local`, `.git`; `whoami` ≠ root | — | IMPLEMENTADO 2026-10-07 (sem multi-stage) |
| TASK-03 | Remover/reescrever os testes legados | ISS-03 | `tests/test_trading_service.py`, `tests/test_aggregator_service.py`, `tests/test_e2e_flow.py` | `pytest tests -q` coleta sem erros | — | IMPLEMENTADO: legados removidos no commit `13c010e`; suíte-base validada em 2026-10-08 (158 aprovados, 1 ignorado) |
| TASK-04 | Testes unitários do domínio (`valuation`, `technical_context`, `recommendation`, `insight_payload`, `historical_series`) com os critérios da seção 6.1 | ISS-03, NFR-06 | `tests/analysis/*` | Cobertura de `app/core/analysis` ≥ 90% | TASK-03 | IMPLEMENTADO (2026-10-08): casos adicionais em `tests/analysis/`; cobertura medida em 100% |
| TASK-05 | Job de CI com pytest + lint antes do build; `latest` apenas em `main` | ISS-05 | `.github/workflows/*` | PR com teste vermelho não publica imagem | TASK-03 | IMPLEMENTADO 2026-10-07 (ruff + pytest --cov-fail-under=45) |
| TASK-06 | Reescrever o README (remover resíduos, apontar para esta spec) | ISS-12 | `README.md` | Nenhuma afirmação contradiz esta spec | — | IMPLEMENTADO (2026-10-08) |

### Fase 1 — Confiabilidade

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-10 | Tirar os `commit()` dos repositórios; unidade de trabalho única no `CoreProcessor` | ISS-01, NFR-01 | *Dado* uma falha forçada em `salvar_insight`, *quando* a mensagem é processada, *então* nenhuma linha nova existe em `historico_acoes` | TASK-04 | IMPLEMENTADO (2026-09-26) |
| TASK-11 | Chave de idempotência para snapshots e insights | ISS-02, NFR-02 | Processar a mesma mensagem 2× gera 1 linha em cada tabela | TASK-10, DEC-01 | IMPLEMENTADO (2026-09-26) |
| TASK-12 | DLQ com `maxReceiveCount` configurável | ISS-06, NFR-03 | Mensagem que sempre falha chega à DLQ após N tentativas | — | IMPLEMENTADO na infra (2026-09-26) |
| TASK-13 | Logger único, JSON, nível via `Settings.log_level` | ISS-08, NFR-04 | Cada evento aparece uma vez; `LOG_LEVEL=DEBUG` habilita logs de debug | — | IMPLEMENTADO (2026-10-08: `JsonFormatter`, handler único e teste de JSON) |
| TASK-14 | Reutilizar o cliente SQS; retry do banco via `Settings` | ISS-09, ISS-10, NFR-07 | Uma instância de cliente por processo; nenhum `os.getenv` fora de `settings.py` | — | IMPLEMENTADO (2026-10-08: SQS já reutilizado; retry DB usa `Settings`) |
| TASK-15 | Usar exclusivamente migrations Flyway da infraestrutura | ISS-07 | Worker não cria/atualiza tabelas; inbox na V11 | DEC-01 | IMPLEMENTADO |
| TASK-16 | Limpeza de código morto e dependências não usadas | ISS-11 | `requirements.txt` só com dependências importadas | — | IMPLEMENTADO (2026-10-08: remoção de `pydantic`/`requests`, UTC aware e dataclass manual removido) |

### Fase 2 — Qualidade financeira

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-20 | Graham com ajuste `× 4,4 / Y`, com `Y` configurável | ISS-F1, REQ-08 | *Dado* `LPA=2`, `g=3`, `Y=4,4`, *então* `V=29`; *dado* `Y=8,8`, *então* `V=14,5` — ambos os casos em `tests/test_valuation.py::test_criterio_aceite_task20_*` | TASK-04, DEC-02 | IMPLEMENTADO (2026-09-27) |
| TASK-21 | Aceitar VPA e calcular o Graham Number como métrica complementar | ISS-F2 | Campo `graham_number` no payload quando houver VPA > 0 | VPA lido de `indicador_fundamentalista` (CVM, pela data de entrega), não do produtor Java | IMPLEMENTADO (2026-09-27): `valuation.graham_number`, trava de `COMPRA_FORTE` em `recommendation.py` |
| TASK-22 | Faixa neutra para `VENDA_VALUATION`; limiares em configuração versionada | ISS-F3, ISS-F4 | Limiares lidos de config; testes cobrem as bordas | TASK-04 | IMPLEMENTADO (2026-09-27): `app/core/analysis/limiares.py`; bordas em `tests/test_recommendation.py` |
| TASK-23 | `versao_payload = "3.0"` com campo `aviso_legal` e rótulos revisados | ISS-F6, REQ-09 | Todo insight contém `aviso_legal`; consumidores informados | DEC-05 | IMPLEMENTADO (2026-10-07; schema aceita N e N−1, alias `recomendacao` preservado) |

### Fase 3 — Análise com histórico

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-30 | Serviço de indicadores sobre `serie_historica`: MM20, volume médio 20d, z-score 52s | ISS-F5, REQ-07 | Funções puras testadas com séries sintéticas | TASK-01, TASK-04 | IMPLEMENTADO (2026-09-26): `app/core/analysis/technical_series.py`, com preço ajustado por proventos; testes em `tests/test_technical_series_analyzer.py` |
| TASK-31 | Conectar `MomentumStrategy` e `MeanReversionStrategy` como sinais técnicos | ISS-F5 | Sinais preenchidos quando houver ≥ 20 candles | TASK-30 | IMPLEMENTADO (2026-09-26): `SerieTecnicaService` grava `sinal_momentum`/`sinal_reversao` em `detalhes_json.contexto_tecnico_serie` (nome real do campo, não `sinais_tecnicos`) e o diário os registra; eles NÃO alteram a recomendação principal, que segue a de valuation |
| TASK-32 | Fonte de P/L setorial para `ValuationStrategy` (ou remover a estratégia) | ISS-F4 | Decisão registrada em DEC; estratégia ativa ou removida | DEC-06 | IMPLEMENTADO (2026-10-08): `ValuationStrategy` mantida apenas como compatibilidade, marcada `ativa = False`; `should_buy`/`should_sell` sempre retornam `False` e teste garante que a regra setorial não influencia a recomendação sem fonte confiável |

### Fase 4 — Validação

| ID | Tarefa | Resolve | Critério de aceite | Depende de | Status |
|---|---|---|---|---|---|
| TASK-40 | Backtest walk-forward sem viés de futuro: snapshot reconstruído com COTAHIST e LPA TTM **com `DT_RECEB` ≤ t** (arquivo-índice do DFP/ITR; defasagem mediana de 79 dias entre fim do exercício e entrega), amostragem mensal, teste congelado de 2023 em diante, contra a média da carteira e o CDI | ISS-F4 | Relatório por classe × horizonte (21/63/126 pregões) com n, acerto vs taxa-base, excesso e IC por bootstrap; mesmos parâmetros → mesmos números | TASK-42, TASK-43; ETL: `DT_RECEB`, COTAHIST 2016+ | PLANEJADO |
| TASK-41 | Recalibrar limiares com base no backtest | ISS-F4 | Nova versão de limiares registrada em DEC (e `VERSAO_REGRA` incrementada) | TASK-40 | IMPLEMENTADO (2026-09-27): `python -m app.validacao.calibracao`; `margem_venda` −15 → −100, `VERSAO_REGRA` 2026.09.27-2, números em `DEC-07`. Score de confiança não recalibrado (fica para depois do diário ter amostra) |
| TASK-42 | Motor de avaliação único para backtest e diário (`app/validacao/avaliador.py`): entrada na abertura do pregão seguinte, saída no fechamento do h-ésimo pregão, custo 0,10% ida e volta, excesso sobre a média da carteira (V5) e sobre o CDI, acerto só para recomendação com direção, janela com salto ≥ 40% marcada como suspeita | ISS-F4 | `tests/test_avaliador.py` (14 casos) | — | IMPLEMENTADO (2026-09-26) |
| TASK-43 | `VERSAO_REGRA` (`app/core/analysis/versao_regra.py`) gravada em todo `detalhes_json`; incrementar a cada mudança que altere a saída | ISS-F4 | Teste fixa a versão atual | — | IMPLEMENTADO (2026-09-26) |
| TASK-44 | Diário de sinais (`python -m app.validacao.diario registrar|avaliar`): um sinal por ativo por pregão por versão, só inclusão (`infra#CTR-11`) | ISS-F4 | `tests/test_diario.py` (16 casos); registrar duas vezes não duplica; horizonte só é avaliado quando vence | TASK-42, TASK-43 | IMPLEMENTADO (2026-09-26) |
| TASK-45 | Agendar `registrar` e `avaliar` todo dia útil após o fechamento (Agendador de Tarefas do Windows chamando `docker compose run`) | ISS-F4 | Um registro por pregão sem intervenção manual | TASK-44 | IMPLEMENTADO VIA INFRA (2026-10-08): rotina da manhã da infraestrutura já cobre execução diária dos CLIs; comandos continuam documentados no README (`python -m app.validacao.diario registrar|avaliar`). Validação operacional pertence ao hub de infra |
| TASK-46 | Backfill histórico de proventos (2017+) para o backtest todo, não só a janela móvel de ~12 meses da B3 ao vivo | ISS-F7 | Fonte alternativa à B3 ao vivo (que só cobre ~12 meses por coleta) identificada e carregada; retorno do backtest inteiro passa a incluir proventos, não só os sinais recentes | TASK-40; `provento_distribuido` (gestor) | IMPLEMENTADO (2026-10-07): `FonteProventos` combina B3 com DVA/CVM (`provento_contabil`) antes do primeiro evento B3; backtest já consome por papel e ajusta escala por eventos corporativos |
| TASK-47 | `app/validacao/proventos.py`: distinguir provento por classe de ação (ON/PN) via ISIN, em vez de usar o maior valor entre classes | ISS-F7 | Teste com evento de valores diferentes por classe usa o valor da classe correta, não o maior | TASK-46 | IMPLEMENTADO (2026-10-07): `agrupar_por_papel_e_data` usa `cvm_ticker.isin`; diário e backtest passam a buscar proventos por ticker, com fallback por emissor |
| TASK-50 | Placar com intervalo de confiança: `agregar` grava desvio-padrão do excesso (CDI e carteira); acerto com Wilson 95% | ISS-F4, `infra#TASK-30` | `backtest_placar` com `desvio_excesso_*`; leitura "acima da base" exige IC acima da taxa-base | — | IMPLEMENTADO (2026-09-27) |
| TASK-51 | Backtest sobre o universo amplo (`universo_backtest`, point-in-time, com deslistadas) e régua = média do universo | ISS-F4, `infra#TASK-31` | ≥ 3× janelas; cobertura por ano nas observações | TASK-50, **TASK-59 (bloqueador achado em 27/09)** | CONCLUIDO (2026-09-27): COTAHIST amplo 2016-2026 (1.785 códigos, 1,16 mi pregões); universo point-in-time em `app/validacao/universo.py` (≥ 200 pregões e ≥ R$ 5 mi/dia no ano anterior, sem units nem BDRs, com deslistadas): 93 a 191 ações por ano; DFP 2016-2025 de 249 empresas (`etl --universo-backtest`); backtest com 258 ativos, 15.732 amostras (5×); IC por bootstrap em blocos de meses (V12, `bootstrap.py`). **Resultado: nenhuma regra com vantagem distinguível** — acerto e excesso cruzam a base em todas as linhas, exceto a compra moderada da v1 antiga (+1,1% s/ carteira, IC +0,3 a +2,0). 38 papéis sem balanço por troca de código: `infra#TASK-45` |
| TASK-52 | Momentum e reversão à média como regras próprias do backtest | ISS-F5, `infra#TASK-32` | Placar próprio; DEC sobre entrar na recomendação | TASK-51 | IMPLEMENTADO (2026-10-07): `app.validacao.backtest` adiciona `TECNICO_MOMENTUM_2026.10.07-1` e `TECNICO_REVERSAO_2026.10.07-1` em `REGRAS`; sinais são calculados só com candles disponíveis até o dia da amostra e entram no placar sem pesar na recomendação principal; testes em `tests/test_backtest_tecnico.py`. Pendente: executar contra banco real e registrar DEC de combinação |
| TASK-53 | Curva de calibração do `confianca_score` | ISS-F4, `infra#TASK-33` | Acerto por faixa de score; DEC recalibrar/retirar | TASK-51 | IMPLEMENTADO (2026-10-08): função pura `app.validacao.confianca.curva_por_faixa()` agrupa score em faixas, separa sinais sem direção e calcula taxa de acerto; teste sintético cobre faixas, score fora de 0–100 e `acerto=None`. Execução em base real e DEC de recalibração ficam para etapa posterior |
| TASK-54 | Crescimento nominal (g + IPCA 12m) ou Y real (Selic − IPCA) na v1 | ISS-F1, DEC-07, `infra#TASK-34` | Fração de vendas estável entre calibração e teste (< 10 p.p.) | TASK-51 | IMPLEMENTADO (2026-09-27): modo G_NOMINAL, DEC-08; aceite < 10 p.p. quase atingido (11,6 p.p.) |
| TASK-55 | `VENDA_VALUATION` → `SEM_MARGEM` sem direção até haver vantagem medida | ISS-F3, `infra#TASK-35` | Contrato versionado com gestor e painel | TASK-50 | IMPLEMENTADO (2026-10-07; produção grava `SEM_MARGEM` com direção 0; histórico `VENDA_VALUATION` continua legível) |
| TASK-56 | Placar separando janelas com e sem dado de provento | ISS-F7, `infra#TASK-36` | Contagem de janelas ajustadas no placar | — | IMPLEMENTADO (2026-09-27): coluna `janelas_com_provento` (infra V10), exibida no painel; no backtest de 2017-2026, 1.273 de 22.980 janelas (5,5%) têm provento — a fonte cobre só os últimos ~12 meses |
| TASK-57 | Recalibrar no universo amplo pelo limite inferior do IC | ISS-F4, `infra#TASK-37` | DEC com limiares e intervalo | TASK-51, TASK-54 | CONCLUIDO (2026-09-27), sem mudança de limiares — ver `gerar-insights#DEC-09`: nenhuma das 1.944 combinações válidas teve o limite inferior do IC da separação acima de zero na calibração (melhor: −2,1 a +3,2 p.p.) |
| TASK-58 | Decidir v1 × v2 | `infra#TASK-38` | DEC; `VERSAO_REGRA` incrementada | TASK-57 | IMPLEMENTADO (2026-10-08): ver `DEC-10`; manter regra atual como principal e v2/ranking como modo sombra/experimental até placar próprio demonstrar vantagem |
| TASK-59 | Ingestão de COTAHIST amplo (todos os tickers negociados por ano, não só os 31 monitorados) - pré-requisito real do TASK-51/infra#TASK-31 | ISS-F4, `infra#TASK-31` | `cotacao_b3_diaria` com centenas de símbolos/ano, incluindo os que saíram de negociação; confirmado com `COUNT(DISTINCT simbolo)` bem acima de 36 | — | CONCLUIDO (2026-09-27): carga ampla rodada (implementação da sessão paralela, a1ed827..f3b3a1c; carga e verificação pela sessão "Projeto para hoje") — 1.785 códigos em `cotacao_b3_diaria` |

---

## 9. Decisões

| ID | Pergunta | Opções | Status | Decisão / data |
|---|---|---|---|---|
| DEC-01 | Quem é dono do schema MySQL? | Infraestrutura/Flyway exclusivamente; worker não executa DDL nem Alembic | IMPLEMENTADO — `infra#DEC-01`, V1–V11 | — |
| DEC-02 | Qual taxa usar como `Y` no Graham ajustado? | NTN-B longa (real) / Selic / CDI / valor fixo configurável | IMPLEMENTADO (2026-09-27): **Selic meta vigente** (SGS 432, `indice_macro.codigo_serie = 'SELIC'`, % a.a.), a do dia da análise; no backtest, a vigente na data do sinal. Motivos: é a única taxa livre de risco que o ecossistema já coleta (o gestor a grava e o painel a mostra em Índices); NTN-B longa exigiria ingerir os preços do Tesouro Direto e fica como evolução. Sem taxa disponível, o insight sai `SEM_DADOS` em vez de cair na fórmula sem ajuste (misturaria duas regras sob a mesma versão). A fórmula de 1962 (`Y = 4,4`, fator 1) continua calculada em `cenarios_graham_sem_ajuste_juros`, **só como referência histórica** — não entra na recomendação. Consequência conhecida: `Y` nominal com `g` real (0/3/5) é conservador; tratado nas sessões de ISS-F2/F3 | — |
| DEC-03 | Política de retenção de `historico_acoes` | RESOLVIDO (2026-10-08): manter histórico bruto integral por enquanto. Motivo: a tabela é base de auditoria/idempotência e ainda não há evidência de pressão de armazenamento; agregação/expurgo só deve virar nova tarefa quando houver métrica real de crescimento, backup ou custo | IMPLEMENTADO | — |
| DEC-04 | DynamoDB: implementar ou remover do projeto? | implementar / remover | IMPLEMENTADO: removido (config morta em `settings.py`/`aws_config.py`, nunca usada) | — |
| DEC-05 | Nomenclatura das recomendações | manter COMPRA/VENDA / "sinal quantitativo" (ex.: `SINAL_POSITIVO_FORTE`) | RESOLVIDO (2026-10-07) | Adotado **sinal quantitativo** no payload 3.0: `COMPRA_FORTE`→`SINAL_POSITIVO_FORTE`, `COMPRA_MODERADA`→`SINAL_POSITIVO`, `VENDA_VALUATION`→`SEM_MARGEM` (sem direção), `MANTER`→`NEUTRO`. O campo legado `recomendacao` permanece como alias com os valores novos durante a transição; versões 2.1 históricas continuam aceitas |
| DEC-06 | Fonte de P/L setorial | RESOLVIDO (2026-10-08): não usar API externa nem tabela manual neste ciclo; desativar a `ValuationStrategy` setorial até existir fonte point-in-time validada ou fatores setoriais medidos no backtest | IMPLEMENTADO | `TASK-32` |
| DEC-07 | Limiares da v1 depois do ajuste de juros (TASK-41) | manter os da fórmula sem juros / calibrar por backtest | IMPLEMENTADO (2026-09-27): **calibrados**. Protocolo (`app/validacao/calibracao.py`): grade de 1.440 combinações de `multiplo_base`, margens e earnings yield, avaliada só na calibração (sinais até 2022-12-31, horizonte 63 pregões); objetivo = excesso médio sobre a carteira das compras menos o das vendas, com ≥ 60 janelas em cada lado e venda em no máximo 50% das janelas (sem esta trava a primeira passada escolheu 92% de venda no teste). O teste (2023+) foi olhado uma vez, como veredito. Adotado: `margem_venda = −100`; demais limiares mantidos (empatavam no topo). Medido no teste, 63 pregões: separação compra × venda **3,4 p.p.** (v1 com −15: 2,9; v1 antiga sem juros: 2,4); compras 24 janelas, acerto 58% (taxa-base 52%), +3,6% sobre a carteira; vendas 69% das janelas, acerto 51% (≈ taxa-base: sem vantagem). **Não generalizou**: a fração de vendas (49% na calibração, 69% no teste) depende do regime de juros, porque `Y` é nominal e `g` é real — com Selic de 2–6% (calibração) o fator 4,4/Y é ~1, com 11–15% (teste) é ~0,3. Próximo passo: crescimento nominal (`g` + IPCA), como a v2 já faz | — |
| DEC-08 | Como combinar juros e crescimento no Graham da v1 (TASK-54)? | G_REAL (Y = Selic, g real — a 2026.09.27-2) / G_NOMINAL (Y = Selic, g = real + IPCA 12m) / Y_REAL (Y = Selic − IPCA 12m, g real) | IMPLEMENTADO (2026-09-27): **G_NOMINAL**, `VERSAO_REGRA` 2026.09.27-3. Motivo a priori (antes dos números): nominal com nominal — o G_REAL misturava as bases e por isso a margem acompanhava a Selic (DEC-07). Medição (`calibracao.py`, os três modos com os mesmos critérios; limiares escolhidos só na calibração, 63 pregões): fração de vendas calibração → teste G_REAL 49% → 70% (21,5 p.p.), **G_NOMINAL 20% → 32% (11,6 p.p.)**, Y_REAL 9% → 26% (16,8 p.p.); separação compra × venda no teste 3,2 / 3,1 / 2,3 p.p. O aceite da TASK-54 (< 10 p.p.) **não foi atingido por completo**, mas o G_NOMINAL ficou perto e é o melhor dos três. Limiares: `margem_venda` −150 (calibrado), demais mantidos (empatavam; ficaram os mais conservadores). No backtest de teste: compras fortes 48 janelas, +4,6% sobre a carteira; vendas 334 janelas, acerto 54,8% contra taxa-base de 46,5% e −1,0% sobre a carteira — primeira vantagem de venda medida. Nas cotações de 27/09: 14 vendas, 12 manter, 1 compra (antes 24 vendas de 26). Ressalva: a trava de estabilidade medida só dentro da calibração (2017–2019 × 2020–2022) não discriminou os modos, porque a Selic média dos dois sub-períodos é parecida; a escolha entre modos usou o critério do teste que a própria TASK-54 definiu | — |
| DEC-09 | Recalibrar os limiares da v1 no universo amplo (TASK-57, `infra#TASK-37`)? | adotar a melhor combinação / manter a 2026.09.27-3 | RESOLVIDO (2026-09-27): **manter**, sem mudança de `VERSAO_REGRA`. Protocolo (`calibracao.py`): universo point-in-time de 258 ativos (15.732 amostras), grade de 3 modos de juros × 4 múltiplos × margens × earnings yield (1.944 combinações válidas: amostra mínima, ≤ 50% de vendas, estável entre 2017–2019 e 2020–2022), 30 finalistas pela separação pontual, escolha pelo **limite inferior do IC 95% da separação compra × venda por bootstrap em blocos de meses**, só na calibração. Resultado: **nenhum limite inferior acima de zero** (melhor: Y_REAL, múltiplo 15, venda −100 → separação +0,7 p.p., IC −2,1 a +3,2; atuais: IC −2,4 a +3,1). No teste: melhor +1,0 p.p. (IC −0,6 a +3,0), atuais −0,7 p.p. (IC −3,7 a +2,5), v1 antiga 0,0 (IC −2,7 a +2,3). Trocar para a "melhor" seria escolher ruído. Conclusão: no universo amplo, a família de regras de valuation Graham + margem + earnings yield **não tem vantagem mensurável**; afinar limiares não resolve. Próximos passos estão fora de limiar: medir outros sinais (momentum e reversão, TASK-52; qualidade — ROE, dívida — como filtro) e seguir o diário. Relatório completo da calibração: saída de `python -m app.validacao.calibracao` | — |
| DEC-10 | Decidir v1 × v2 | RESOLVIDO (2026-10-08): manter a regra atual/v1 calibrada como principal e conservar v2/ranking em modo sombra/experimental. Motivo: `DEC-09` mostra que escolher limiar ou variante por ganho pontual seria ruído; v2/ranking só deve ser promovida após placar próprio, com intervalo de confiança favorável e versão de regra incrementada | IMPLEMENTADO | `TASK-58` |

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

## Revisão integrada de 2026-09-27

| Entrega | Estado | Evidência e limite |
|---|---|---|
| Proprietário único do schema | IMPLEMENTADO | Infra/Flyway: V1 bootstrap, V11 inbox; serviços não executam migrations |
| Eventos e recomendações | IMPLEMENTADO | schemas canônicos em infra/contracts; enum gerado em Java, Python e JS; versões desconhecidas ficam para DLQ |
| Leituras HTTP e idempotência | IMPLEMENTADO | GET sem persistência/publicação; inbox e efeitos na mesma transação; ACK posterior ao commit |
| Verificação desta entrega | EM ANDAMENTO | Resultados registrados em infra/VERIFICACAO-2026-09-27.md; não representa deploy no banco em uso |

## Plano LAC: 9 lacunas de assertividade (proposta de 30-09-2026, EM AVALIAÇÃO)

Plano completo, fontes e a migração única **V16** em `infra-b3-ecossytem/SPEC.md`, seção Plano LAC.

**Por que.** Execução 14 do backtest, período de teste (2023 em diante): nenhuma recomendação direcional tem intervalo de 95% do acerto acima da taxa-base (ex.: COMPRA_FORTE em 126 pregões, 40,4% contra 51,4% de base; VENDA_VALUATION em 63 pregões, 52,8% com IC 43,9%–62,3%). Na calibração os números eram melhores: sinal de regra ajustada ao passado. Este serviço cobre **L1 e L2 no cálculo de retorno, L5, L6, L7, L8, L9 e o método de avaliação**.

### LAC-INS-1: retorno total com proventos (L1)

- `avaliador.py` soma hoje só os proventos de `provento_distribuido` (janela de ~12 meses): de 2017 a 2024 o retorno sai **sem dividendos**, o que penaliza pagadoras (bancos, elétricas) e favorece VENDA_VALUATION.
- Passa a somar os proventos da DVA (`provento_contabil.por_acao`) na mesma regra do sinal e da régua (carteira):
  - **Data:** a marca ex do COTAHIST (`cotacao_b3_diaria.marca_ex` em ED, EJ, EDJ…). O total do trimestre é repartido entre as datas ex daquele trimestre.
  - **Sem marca:** vale a `data_entrega` do documento.
  - Onde `provento_distribuido` existir (evento com valor e data-com), ele prevalece.
- `janelas_com_provento` do placar passa a refletir as duas fontes.

### LAC-INS-2: preço ajustado por desdobramento (L2)

- `RepositorioCotahist.series` aplica `evento_corporativo.fator_preco` acumulado **na leitura**. O COTAHIST bruto não é regravado.
- A regra que descarta janelas com salto acima de 40% continua, mas só para saltos **sem** evento correspondente. Medir quantas janelas voltam a contar (ex.: RCSL3, −76% em 10-03-2026 com marca EB, hoje descartada como "provável desdobramento").
- Preços já chegam divididos pelo FATCOT (LAC-ETL-7): AZUL53 e GOLL54 deixam de entrar multiplicados por 1.000.000 e 1.000.

### LAC-INS-3: fatores de preço (L5)

Cálculo mensal (primeiro pregão do mês, só com pregões anteriores) em `fator_valor`: `MOMENTO_12_1`, `VOLATILIDADE_12M`, `LIQUIDEZ_63D`, `BETA_12M`, `DRAWDOWN_12M`, sobre o preço ajustado (LAC-INS-2). Comando: `python -m app.fatores calcular --desde AAAA-MM`.

Dois fatores a mais, com os campos novos do COTAHIST (entram em `fator_definicao`, sem migração nova):
- `SPREAD_MEDIANO_63D`: `(melhor oferta de venda − melhor oferta de compra) / preço médio`, mediana em 63 pregões; direção −1.
- `DISTANCIA_VWAP`: fechamento sobre o preço médio do dia (`preco_medio`); direção 0, só para estudo.

**Custo do backtest pelo spread real:** metade do spread mediano do ativo em cada ponta, com piso nos 0,10% atuais. O custo fixo subestima ações pouco líquidas (p90 do spread em 3,4%).

### LAC-INS-4: fatores de qualidade e valor (L6)

`ROIC`, `ALAVANCAGEM`, `MARGEM_BRUTA`, `ACCRUALS`, `PIOTROSKI`, `CRESCIMENTO_LPA`, `EARNINGS_YIELD`, `BOOK_TO_MARKET` e `DIVIDEND_YIELD`, lendo o `indicador_fundamentalista` **vigente na data** (o de maior `data_entrega` até a data de referência: `DadosPontoNoTempo`). Piotroski usa as 4 contas novas (LAC-ETL-5); sem elas, o escore fica `NULL`, sem valor parcial.

### LAC-INS-5: comparação no setor (L7)

- `percentil_setor` e `grupo_setor` em cada `fator_valor`, pelo `setor_grupo` (revisado em LAC-INFRA-2).
- Regra de valuation por grupo (`setor_grupo.regra_valuation`): GRAHAM para a maioria; PL_SETOR ou PVP_SETOR para financeiro; DIVIDENDOS para utilidade pública. A regra atual passa a ser uma versão entre outras no placar, não a única.

### LAC-INS-6: fatores de evento (L8)

`FATOS_RELEVANTES_90D` e `AVISOS_PROVENTOS_180D`, contando `comunicado_cvm` por `data_entrega`, nunca por `data_referencia` (36 datas inválidas).

### LAC-INS-7: fatores de referência próprios (L9)

`fator_mercado_mensal`, construídos com COTAHIST e CVM no lugar do NEFIN:

| Fator | Carteira |
|---|---|
| MKT | Média do universo menos CDI |
| SMB | Menor menos maior valor de mercado |
| HML | Maior menos menor book-to-market |
| WML | Maior menos menor momento |
| IML | Menor menos maior liquidez |
| QMJ | Maior menos menor qualidade |

Uso: regressão do retorno da carteira do sinal contra esses fatores. O alfa (intercepto) mostra se a regra traz algo além de fatores conhecidos.

### LAC-INS-8: método de avaliação por ranking

- **Ranking entre ações.** Todo mês, ordenar o universo pelo score de cada versão de regra e gravar:
  - `backtest_ranking_mes`: correlação de Spearman entre o score e o retorno seguinte, por horizonte;
  - `backtest_ranking_quintil`: retorno médio de cada quintil.
- **Janelas sucessivas** (`esquema_validacao = 'JANELAS_SUCESSIVAS'`): treino expandindo desde 2011, teste de 12 meses, avançando ano a ano; cada janela registrada em `janela`.
- **Registro de tentativas:**
  - `backtest_execucao.hipotese` é preenchida **antes** de rodar: o que se espera e por quê;
  - `numero_tentativa` conta as tentativas da mesma família;
  - a melhor de N tentativas precisa superar um limiar corrigido por N.
- **Juízes intocados:** o período de 2023 a 2026 já foi visto e não serve mais sozinho para promover regra. Valem as janelas sucessivas mais o diário ao vivo (primeiros horizontes vencem a partir do fim de outubro de 2026).
- O método por classes (`backtest_placar`) continua, para comparação com o histórico.

### LAC-INS-9: placar e promoção de regra

Uma versão de regra só é promovida se, nas janelas de teste:
1. o intervalo de 95% da correlação de ranking média ficar acima de zero;
2. a diferença entre o quintil 5 e o 1 ficar positiva depois de custos (0,1% ida e volta);
3. o alfa contra os fatores de referência (LAC-INS-7) não for negativo;
4. o diário ao vivo não contradisser.

### Aceite

- Backtest de 2011 a 2026 com proventos e desdobramentos, nos dois métodos (classes e ranking).
- Ao menos 3 versões novas medidas (valor, valor com qualidade, valor com momento), cada uma com `hipotese` e `numero_tentativa` registrados antes de rodar.
- Testes para: soma de proventos da DVA sem dupla contagem com `provento_distribuido`; ajuste de preço por evento; fatores sem olhar o futuro (fator do mês M usa só dados até o pregão de referência); correlação de ranking e quintis em série sintética conhecida.

---

## Plano GEM: lote gradual de opiniões com Gemini (2026-10-08)

**Status:** PLANEJADO · **Contexto e decisões:** `insider-ia-b3-ecossytem/SPEC.md` seção 13 (DEC-IA-06..09) · **Coordenação:** hub, linhas `GEM-*`.

**Escopo deste repositório (grupo B).** Só o worker `app/opiniao/**`, `tests/opiniao/**` e as chaves novas em `app/config/settings.py`. Não editar nada do `insider-ia`, do painel, do gestor nem da infra. O contrato consumido é o **CTR-IA-01 v1.1** (`POST /opiniao/ativo`), definido na seção 13.3 do SPEC do insider-ia; até o serviço publicar a rota, os testes usam o servidor HTTP falso que já existe em `tests/opiniao/test_cliente_ia.py`. Sem migration: `opiniao_ia` (V22) já tem `dossie_hash` e a chave única `(simbolo, data_pregao, horizonte_pregoes, modelo, versao_prompt)`.

**Problema.** Hoje o lote faz 1 chamada por ativo e horizonte (~105 ativos × 3 = ~315 por pregão). Com o Gemini como provedor principal (cota gratuita limitada), isso estoura a cota no primeiro minuto e gasta chamadas com ativos que ninguém olha ou que não mudaram.

**Meta.** No máximo `LOTE_MAX_GEMINI` ativos (padrão 25) por pregão vão ao serviço, uma chamada por ativo; o resto grava pela regra local, sem chamar o serviço.

| ID | Tarefa | Arquivos | Depende | Aceite | Status |
|---|---|---|---|---|---|
| TASK-GEM-L1 | **Uma chamada por ativo (CTR-IA-01 v1.1).** `ServicoIA.opinar_ativo(pedido) -> RespostaAtivo` chamando `POST /opiniao/ativo` com os 3 horizontes; `pedido_do_ativo(simbolo, data_pregao, dossie, ausentes, versao_regra, uso="lote")`. Cada item da resposta vira uma linha com `modelo = item.modelo` (quem respondeu) e `versao_prompt = skills_versao`. Se a rota responder 404 (serviço antigo), cai no `POST /opiniao` v1.0 por horizonte, sem erro | `app/opiniao/cliente_ia.py`, `app/opiniao/gerar.py`, `tests/opiniao/test_cliente_ia.py` | CTR-IA-01 v1.1 (insider-ia 13.3) | Servidor falso: 1 requisição grava 3 linhas; 404 ⇒ 3 requisições v1.0; item com `origem=REGRA` grava `modelo=regra` | IMPLEMENTADO (2026-10-08) |
| TASK-GEM-L2 | **Fila de prioridade.** `priorizar(db, data_pregao, simbolos) -> list[str]` em ordem: (1) favoritos (`ativo_monitorado.ativo = TRUE AND tipo_coleta = 'COTACAO_E_HISTORICO'`, V13 — conferir o valor real antes de codar); (2) demais monitorados (`ativo_monitorado.ativo = TRUE`); (3) ativos cujo conjunto (opinião permitida mais forte, risco) mudou em algum horizonte desde o pregão anterior; (4) variação do dia acima de 2 desvios-padrão de 63 pregões; (5) maior liquidez (`LIQUIDEZ_63D`). Corta em `LOTE_MAX_GEMINI`. Os demais gravam pela regra local sem chamar o serviço | `app/opiniao/prioridade.py`, `app/opiniao/repositorio.py`, `app/opiniao/gerar.py`, `tests/opiniao/test_prioridade.py` | — | Teste com repositório falso: ordem exata nos 5 critérios, sem repetir símbolo, corte respeitado; `--simbolo` explícito ignora o corte | IMPLEMENTADO (2026-10-08) |
| TASK-GEM-L3 | **Pular quem não mudou e parar quando a cota acabar.** (a) Se já existe linha `origem=MODELO` do mesmo símbolo com o mesmo `dossie_hash` em pregão anterior, copia a opinião para o pregão novo (mesmo `modelo`/`versao_prompt`, `tentativas=0`) sem chamar o serviço e conta em `Resumo.reaproveitadas`. (b) Se a resposta trouxer `cota.gemini_disponivel = false`, os ativos restantes do lote vão pela regra local sem chamar o serviço e contam em `Resumo.sem_cota`. (c) Ativo prioritário cujo pregão só tem linha `REGRA` é reenviado na execução seguinte (mesmo pregão), até ter `MODELO` | `app/opiniao/gerar.py`, `app/opiniao/repositorio.py`, `tests/opiniao/test_gerar_lote.py` | L1, L2 | Testes: hash igual ⇒ nenhuma requisição e linha copiada; `gemini_disponivel=false` no 3º ativo ⇒ do 4º em diante nenhuma requisição; segunda execução só reenvia prioritários com `REGRA` | IMPLEMENTADO (2026-10-08) |
| TASK-GEM-L4 | **Configuração e resumo.** `LOTE_MAX_GEMINI` (25) e `IA_TIMEOUT_S` (de 300 para 200) em `Settings`; log final do lote com `priorizados`, `chamadas`, `reaproveitadas`, `sem_cota`, `modelo`, `regra`, `falhas_do_servico`; flag `--sem-limite` para rodar todos (uso manual) | `app/config/settings.py`, `app/opiniao/gerar.py`, `tests/opiniao/test_gerar_lote.py` | L1..L3 | Linha de resumo com todos os campos; `--sem-limite` ignora o corte | IMPLEMENTADO (2026-10-08) |

**Aceite do plano GEM no worker.** Rodando o lote de um pregão com o serviço no ar: no máximo `LOTE_MAX_GEMINI` requisições ao `ia-opiniao`; nenhuma requisição para ativo fora da fila; linhas `REGRA` iguais às de hoje para os demais (mesmo critério de TASK-IA-03); `pytest tests/opiniao -q` verde.

---

## Plano OPR: diário operacional simulado (2026-10-08)

**Status:** PLANEJADO · **Contexto:** `infra-b3-ecossytem/SPEC.md`, Plano OPR. Este worker é o dono das regras operacionais simuladas: elegibilidade, entrada, tamanho de posição, saída, custos e diário. O resultado ainda é paper trading; não autoriza capital real.

**Meta.** Converter sinais e fatores já existentes em operações simuladas auditáveis, com comparação líquida contra CDI. A saída principal é um diário de 3 a 6 meses que diga se o sistema está `NAO_OPERAVEL`, `EM_OBSERVACAO`, `PAPER_TRADING_ELEGIVEL` ou `BLOQUEADO`.

### Tarefas desta aplicação

| ID | Tarefa | Arquivos | Depende | Aceite | Status |
|---|---|---|---|---|---|
| OPR-INS-1 | **Elegibilidade operacional.** Criar módulo `app/operacional/elegibilidade.py` lendo liquidez do ETL: volume financeiro 63d, número de negócios 63d, buracos na série, status de ajuste de preço, fundamento point-in-time e eventos bloqueantes | `app/operacional/**`, `tests/operacional/**` | infra#OPR-INFRA-1; etl#OPR-ETL-1..4 | Ativo líquido passa; ativo ilíquido, sem fundamento vigente ou com salto sem evento é bloqueado com motivo estruturado | IMPLEMENTADO (Sessão 01, 2026-10-10): `app/operacional/elegibilidade.py` (puro: faixa ALTA/MEDIA/INSUFICIENTE pela DEC-OPR-1, spread ausente rebaixa uma faixa; bloqueios SEM_ATR, SERIE_SEM_AJUSTE, EVENTO_CORPORATIVO_RECENTE, FATO_RELEVANTE_RECENTE e SEM_FUNDAMENTO_VIGENTE, cada um com código/detalhe/valor/limite), `repositorio.py` (lote por pregão, tudo com data <= pregão; fundamento por CNPJ, para units e outras classes) e `servico.avaliar_pregao` (função interna chamada pelo diário OPR-INS-4; sem comando, DEC-AGT-1). Limites lidos de `regra_operacional` (OPR-2026.10.10-1). Banco local, 2026-10-09: 381 ativos, 114 elegíveis (ALTA 76, MEDIA 59, INSUFICIENTE 246). Lacuna de dados, não de regra: 21 ativos líquidos (BPAC11, TAEE11, KLBN11, SANB11, MOTV3...) ficam bloqueados por SEM_FUNDAMENTO_VIGENTE porque o ETL não tem essas empresas em `cvm_ticker` nem `indicador_fundamentalista` (ver etl ISS-E18). Testes adiados por decisão do usuário |
| OPR-INS-2 | **Sizing teórico.** Criar `risco.py` com capital teórico configurável, risco máximo por operação, exposição máxima por ativo/setor e redutor por volatilidade/liquidez | `app/operacional/risco.py`, `app/config/settings.py` | OPR-INS-1 | Para capital de R$ 100 mil, a posição nunca excede limites configurados e cai para zero quando elegibilidade falha | PLANEJADO |
| OPR-INS-3 | **Regra de saída.** Criar `saida.py` com saída por mudança de sinal, stop por volatilidade/drawdown, prazo máximo da tese, perda de liquidez e evento relevante | `app/operacional/saida.py` | OPR-INS-1, OPR-INS-2 | Testes cobrem cada motivo de saída e prioridade quando mais de um motivo ocorre no mesmo pregão | PLANEJADO |
| OPR-INS-4 | **Diário operacional.** Criar a etapa do diário, executada pela rotina diária (start único; sem comando manual, DEC-AGT-1), para abrir/fechar operações simuladas, aplicar custos, calcular retorno bruto, retorno líquido, CDI, excesso e drawdown | `app/operacional/diario.py`, repositórios novos | infra#OPR-INFRA-1; OPR-INS-1..3 | Rodar duas vezes o mesmo pregão não duplica; operação fechada tem preço, custo, retorno líquido e motivo de saída | PLANEJADO |
| OPR-INS-5 | **Custos e IR estimado.** Criar `custos.py` com custo fixo, slippage por spread/liquidez e imposto estimado separado do resultado pós-custos | `app/operacional/custos.py` | OPR-INS-4; etl#OPR-ETL-2 | Diário exibe `resultado_bruto`, `resultado_pos_custos` e `resultado_pos_imposto_estimado`; ausência de dado de spread usa fallback conservador | PLANEJADO |
| OPR-INS-6 | **Trava de operabilidade.** Calcular status do sistema por janela: mínimo 63 pregões, retorno líquido > CDI, drawdown abaixo do limite, zero violação de liquidez e amostra mínima de operações encerradas | `app/operacional/status.py` | OPR-INS-4, OPR-INS-5 | Sistema começa `NAO_OPERAVEL`, vai para `EM_OBSERVACAO` durante coleta e só vira `PAPER_TRADING_ELEGIVEL` cumprindo todos os critérios | PLANEJADO |
| OPR-INS-7 | **Eventos operacionais.** Publicar eventos `operacional.*.v1` após diário avaliado, posição aberta/fechada e alerta de risco, sem conhecer Telegram ou painel | mensageria existente | infra#OPR-INFRA-2; OPR-INS-4 | Payload passa nos JSON Schemas e contém `schemaVersion`, `eventId`, `correlationId`, `versao_regra` e `dataPregao` | PLANEJADO |

### Configurações previstas

| Setting | Padrão inicial |
|---|---|
| `OPERACIONAL_CAPITAL_TEORICO` | `100000` |
| `OPERACIONAL_RISCO_POR_OPERACAO` | `0.005` |
| `OPERACIONAL_EXPOSICAO_MAX_ATIVO` | `0.05` |
| `OPERACIONAL_EXPOSICAO_MAX_SETOR` | `0.20` |
| `OPERACIONAL_CUSTO_FIXO_BPS` | `10` |
| `OPERACIONAL_MIN_PREGÕES` | `63` |
| `OPERACIONAL_STOP_ATR` | `2` (stop inicial = entrada − 2 × ATR14) |
| `OPERACIONAL_TRAILING_ATR` | `3` (stop móvel, armado após +1 ATR de lucro) |
| `OPERACIONAL_MAX_PARTICIPACAO_ADTV` | `0.01` (posição ≤ 1% do volume financeiro médio de 21 pregões) |
| `OPERACIONAL_MAX_POSICOES` | `15` |
| `OPERACIONAL_POSICAO_MINIMA` | `500` (R$; abaixo disso não abre) |
| `OPERACIONAL_REDUTOR_LIQUIDEZ_MEDIA` | `0.5` |
| `OPERACIONAL_REDUTOR_VOL_P80` | `0.75` |
| `OPERACIONAL_DIAS_ILIQUIDO_SAIDA` | `5` |
| `OPERACIONAL_REGRAS_IR` | `ir/2026.json` (regras fiscais versionadas por vigência) |

### Parâmetros fixados (DEC-OPR-1, 2026-10-10)

Decisão do usuário: o plano OPR passa a ter valores, não só intenções. Os números abaixo são o ponto de partida do paper trading; mudar qualquer um é nova `versao_regra` em `regra_operacional` (nunca editar a versão em uso). Não é recomendação de investimento.

**Liquidez (OPR-INS-1, sobre `ativo_liquidez_diaria` do ETL, janela de 63 pregões anteriores ao pregão da decisão).**

| Critério | Mínimo para entrar |
|---|---|
| Volume financeiro médio (`volume_financeiro_medio_63d`) | R$ 5 milhões/dia |
| Negócios médios (`negocios_medio_63d`) | 500/dia |
| Presença (`presenca_63d`) | 95% dos pregões |
| Spread mediano (`spread_mediano_63d` = (melhor venda − melhor compra) ÷ preço médio) | ≤ 0,5%; ausente ⇒ cai uma faixa e o custo usa a reserva conservadora |

Faixas: `ALTA` (o dobro de cada mínimo), `MEDIA` (passa nos mínimos), `INSUFICIENTE` (bloqueado, motivo estruturado). Posição aberta só sai por liquidez após `OPERACIONAL_DIAS_ILIQUIDO_SAIDA` pregões seguidos em `INSUFICIENTE`.

**Tamanho de posição (OPR-INS-2).**
1. `quantidade_risco = (capital × OPERACIONAL_RISCO_POR_OPERACAO) ÷ (OPERACIONAL_STOP_ATR × ATR14)`.
2. Limites (vale o menor): `OPERACIONAL_EXPOSICAO_MAX_ATIVO` × capital; espaço restante em `OPERACIONAL_EXPOSICAO_MAX_SETOR`; `OPERACIONAL_MAX_PARTICIPACAO_ADTV` × volume financeiro médio de 21 pregões; caixa disponível (sem alavancagem); `OPERACIONAL_MAX_POSICOES` abertas.
3. Redutores multiplicativos: faixa `MEDIA` × `OPERACIONAL_REDUTOR_LIQUIDEZ_MEDIA`; volatilidade acima do percentil 80 do universo × `OPERACIONAL_REDUTOR_VOL_P80`.
4. Arredonda para baixo: lote de 100; resto no fracionário. Valor final < `OPERACIONAL_POSICAO_MINIMA` ⇒ não abre (motivo `POSICAO_ABAIXO_DO_MINIMO`).
5. Caixa não alocado rende CDI no diário.

**Saída (OPR-INS-3).** Decisão no fechamento do pregão D, execução simulada na **abertura de D+1** (nunca no fechamento de D: seria olhar o futuro). Mais de um motivo no mesmo pregão: vale o primeiro.

| Prioridade | Motivo | Gatilho |
|---|---|---|
| 1 | `EVENTO` | Fato relevante na CVM (IPE, `FATO_RELEVANTE`) ou salto de preço sem evento que o explique (OPR-ETL-3) |
| 2 | `STOP` | Fechamento < entrada − `OPERACIONAL_STOP_ATR` × ATR14; após +1 ATR de lucro, fechamento < máxima desde a entrada − `OPERACIONAL_TRAILING_ATR` × ATR14 |
| 3 | `LIQUIDEZ` | `OPERACIONAL_DIAS_ILIQUIDO_SAIDA` pregões seguidos em `INSUFICIENTE` |
| 4 | `SINAL` | Opinião do horizonte da operação vira `SINAL_NEGATIVO` ou `SEM_BASE` |
| 5 | `PRAZO` | Fim do horizonte da tese (21, 63 ou 126 pregões) |

**IR estimado (OPR-INS-5).** Regras em `OPERACIONAL_REGRAS_IR` (JSON com `vigente_desde`), nunca fixas no código; nenhuma consulta automática à Receita. Apuração mensal:
- ações, operação comum: 15% sobre o lucro líquido do mês; **isento se as vendas de ações no mês somarem até R$ 20 mil** (não vale para ETF/FII); prejuízo acumulado compensa lucro futuro da mesma modalidade; IRRF de 0,005% sobre vendas abatido do devido;
- day trade (20%) não ocorre, porque entrada e saída nunca caem no mesmo pregão; se ocorrer, a regra marca a operação como violação;
- proventos: dividendos isentos, salvo a retenção sobre dividendos acima de R$ 50 mil/mês da mesma empresa (reforma do IR vigente em 2026) — **conferir a regra vigente antes de ligar**; JCP pelo valor líquido da retenção (conferir alíquota vigente);
- diário com três linhas: `resultado_bruto`, `resultado_pos_custos`, `resultado_pos_imposto_estimado`.

**Comparação justa com o CDI (OPR-INS-6).** O benchmark é o **CDI líquido de IR** pela tabela regressiva da renda fixa (22,5% até 180 dias, 20% até 360, 17,5% até 720, 15% acima), contado do início da janela. Carteira já tributada contra CDI bruto reprova o sistema injustamente.

### Aceite local

- `pytest tests/operacional -q` cobre elegibilidade, sizing, saída, custos, idempotência e status.
- Nenhuma regra operacional usa fundamento com `data_entrega` posterior ao pregão.
- Toda decisão registra motivo legível de negócio e payload estruturado para o painel.
