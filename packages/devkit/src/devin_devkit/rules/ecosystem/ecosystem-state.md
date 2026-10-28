# Estado do ecossistema (fonte de verdade)

Antes de qualquer afirmação sobre release, distribuição ou auditoria do
ecossistema `devin-*`, ler `devin-powerups/reports/current-state.md`
(gerado semanalmente pelo `ecosystem_sync`) ou consultar as APIs públicas
(GitHub, PyPI, marketplaces). **Nunca** afirmar estado de publicação de
memória — o estado muda a cada ciclo e memória desatualizada vira
relato falso.

## Factos condensados

- As extensões já estão publicadas nos **dois** canais — VS Code
  Marketplace **e** Open VSX. Publicação de extensão nunca é blocker;
  não reportar como pendência.
- **Não criar novos repositórios** — o conjunto de repos do ecossistema
  está fechado.
- O merge é autónomo através do pipeline de review — não bloquear à
  espera de aprovação manual fora do pipeline.
- Estado de PRs e checks consultado **somente** via `gh`
  (`gh pr view`, `gh pr checks`, `gh api`) — nunca inferir de memória
  ou de saídas antigas.
