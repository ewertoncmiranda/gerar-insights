# AGENTS.md — gerar-insights

Instruções para agentes de código (Claude, Codex, outros). O plano e o backlog estão em `SPEC.md`; a coordenação entre repositórios, no hub `infra-b3-ecossytem/SPEC.md` (seção 1A).

## Start único deste repositório

Worker `main.py` (consumidor SQS, sobe com o container) e as etapas chamadas pela **rotina da manhã** da infra (`insights_diarios`, `opiniao.gerar`, `fatores`, diário). O operacional simulado (Plano OPR) não tem comando: `app/operacional/servico.py` é chamado pelo diário operacional (OPR-INS-4), que entra como etapa da rotina.

## Regra: start único, sem ferramentas de linha de comando não pedidas (DEC-AGT-1, 2026-10-10)

Decisão do usuário. Vale para qualquer agente (Claude, Codex, outros) e prevalece sobre planos antigos dos SPECs.

1. **Toda feature roda a partir do start único deste repositório** (abaixo). Nada de "agora rode `python -m ...`" ou "use a flag `--x`" para o usuário fazer à mão.
2. **Não criar comando, flag, subcomando, script avulso ou `__main__` que ninguém pediu** — inclusive para inspeção, diagnóstico, conferência ou backfill. Conferir é papel de teste ou de tela/endpoint de leitura que já existe.
3. **Feature nova entra numa etapa que o start único já executa** (de preferência dentro de uma etapa existente). Precisa de histórico na primeira execução? A própria etapa preenche sozinha quando a tabela está vazia — sem comando de backfill.
4. Na dúvida, perguntar antes de expor um comando.

### Casos em que manter um ponto de entrada é necessário

| Caso | Por quê | Exemplo |
|---|---|---|
| O próprio start único do serviço | É o que sobe/roda o serviço | comando do container no compose |
| Etapa chamada pelo orquestrador único (rotina da manhã) | O orquestrador isola cada etapa, a falha de uma não derruba as outras e o código de saída vira alerta. Não é para uso manual | `infra/scripts/cargas-etl.ps1` chamando `--cotahist`, `--conciliar` (sai com 3 em divergência grave) |
| Migração de schema | Roda no start da stack; Flyway é o único dono do schema | serviço `db-migrate` |
| Registro das tarefas agendadas e backup | O agendador do Windows precisa de um alvo | `registrar-rotinas.ps1`, `backup-mysql.ps1` |
| Recuperação histórica que já existia, quando o usuário pedir | Exceção herdada; feature nova se recupera sozinha no primeiro start | `backfill-historico.ps1` |
| Passo manual único com internet, documentado | Não pode rodar na rede interna | perfil `ia-pull` (baixar modelo do Ollama) |

Fora desses casos, o ponto de entrada deve ser removido ou incorporado ao start único.
