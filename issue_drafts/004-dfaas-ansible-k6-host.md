# Issue: Setup k6-host + playbook run k6 (workspace per target)

## Contesto
k6 deve girare su host separato. Ogni target host (runner) controlla una propria istanza k6 sul k6-host, usando un workspace dedicato per target.

## Obiettivo
- Installare k6 da repo ufficiale sul k6-host.
- Preparare un workspace per target (persistente).
- Definire playbook per copiare script ed eseguire `k6 run` con `--summary-export`.

## Design dettagliato
### Installazione k6
- Usare repo ufficiale (APT) e installare `k6`.
- Verificare `k6 version`.

### Workspace
- Root: `/var/lib/dfaas-k6` (configurabile).
- Per target: `/var/lib/dfaas-k6/<target-name>/`.
- Per run: `/var/lib/dfaas-k6/<target-name>/<run-id>/<config-id>/`.

### Esecuzione k6
- Copiare script `config-<id>.js` in workspace config.
- Eseguire:
  - `k6 run --summary-export summary.json script.js`
- Salvare stdout/stderr in log file dedicato.

## Task dettagliati
- [ ] Playbook `lb_plugins/plugins/dfaas/ansible/setup_k6.yml`:
  - aggiunta repo k6, installazione package
  - creazione workspace root
- [ ] Playbook `lb_plugins/plugins/dfaas/ansible/run_k6.yml`:
  - riceve variabili `k6_target`, `run_id`, `config_id`, `script_path`, `summary_path`
  - copia script nel workspace
  - esegue k6 con `--summary-export`
- [ ] Playbook `lb_plugins/plugins/dfaas/ansible/teardown_k6.yml` (opzionale):
  - cleanup workspace vecchi o mantenere per debug
- [ ] Documentare prerequisiti di rete:
  - k6-host deve raggiungere gateway OpenFaaS del target

## Acceptance criteria
- k6 installato via repo ufficiale.
- Workspace creato per target.
- `run_k6.yml` produce `summary.json` per config.
- Log di esecuzione disponibili nel workspace.

## Test plan
- Eseguire setup su VM pulita.
- Lanciare k6 con script semplice e verificare `summary.json`.

## Dipendenze
- Issue 002 (generator usa playbook run_k6)

