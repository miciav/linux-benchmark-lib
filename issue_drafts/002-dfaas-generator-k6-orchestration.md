# Issue: Generator DFaaS (k6 orchestration, single-config loop, cooldown, dominance)

## Contesto
Il plugin DFaaS deve generare carico con k6 su host separato, una configurazione alla volta. Dopo ogni configurazione deve:
- attendere cooldown (legacy)
- valutare overload (legacy)
- saltare configurazioni dominanti se la precedente e in overload

Tutto senza modificare il core di linux-benchmark-lib.

## Obiettivo
Implementare il generator DFaaS che:
- genera script k6 per **una config per volta**
- lancia k6 via Ansible sul k6-host
- raccoglie summary e metriche Prometheus
- applica cooldown/overload/dominanza
- registra output e config skip

## Design dettagliato
### Loop di esecuzione (alto livello)
1. Calcola combinazioni funzioni e rate (issue 001).
2. Inizializza:
   - `index.csv` (config eseguite)
   - `results.csv` (config eseguite + metriche)
   - `skipped.csv` (config skippate per dominanza o duplicate)
3. Per ogni config:
   - Se dominata da `actual_dominant_config` -> log e append a `skipped.csv`.
   - Se gia presente in `index.csv` -> skip.
   - Per ogni iterazione:
     - Cooldown (legacy): attendi che CPU/RAM/POWER entro soglia e repliche < 2.
     - Genera script k6 per la config.
     - Esegui k6 su k6-host via Ansible (`k6 run --summary-export ...`).
     - Raccogli summary JSON e parse per funzioni.
     - Interroga Prometheus per metriche node/funzioni.
     - Calcola overload nodo + overload funzioni.
     - Scrivi riga su `results.csv`.
     - Se overload per piu di `iterations/2`, marca `actual_dominant_config`.
     - Aggiorna `index.csv`.

### Dominanza (nuova regola)
- B domina A se per tutte le funzioni `rate_B >= rate_A` e per almeno una `rate_B > rate_A`.
- Se A e overload, tutte le successive B dominate vanno skippate.

### Cooldown (legacy)
- Condizioni:
  - CPU, RAM, POWER <= idle + idle * 15%
  - repliche < 2
- Attesa max 180s (abort se superata).

### Overload (legacy)
- Nodo overload se:
  - avg success rate < 0.95 OR
  - CPU > 80% capacita OR
  - RAM > 90% OR
  - almeno una funzione overload
- Funzione overload se:
  - success rate < 0.90 OR
  - repliche >= 15

### K6 summary parsing
- Script k6 deve taggare ogni scenario per funzione (es: `tags: { function: "figlet" }`).
- Usare `handleSummary()` per produrre JSON con:
  - success rate per funzione
  - avg latency per funzione
  - request count per funzione
- Parser usa quel JSON per i campi `success_rate_function_X`, `medium_latency_function_X`.

### Output (legacy-style)
- `results.csv` con header simile a legacy (`function_*`, `rate_*`, metriche, replica, overload flags).
- `skipped.csv` con config skippate.
- `index.csv` con config eseguite e path output.

## Task dettagliati
- [ ] Creare generator DFaaS (CommandGenerator o BaseGenerator custom).
- [ ] Implementare generazione script k6 per config singola.
- [ ] Integrare esecuzione via Ansible (playbook run su k6-host).
- [ ] Implementare parser summary k6 (per funzione) + estrazione latenze.
- [ ] Implementare logica cooldown/overload/dominanza (legacy + nuova dominanza).
- [ ] Implementare `index.csv` e `skipped.csv` come in legacy.
- [ ] Error handling: in caso di failure, loggare config skippata e passare alla successiva.

## Acceptance criteria
- Una sola config attiva alla volta.
- Cooldown rispettato e loggato.
- Overload calcolato come legacy.
- Config dominanti skippate correttamente.
- Summary k6 salvato e parsato per funzione.
- CSV finali coerenti con schema legacy.

## Test plan
- Test manuale con 1-2 funzioni e rate list piccola (es: 0, 10, 20).
- Forzare overload (es: rate alto) e verificare skip dominanti.
- Verificare cooldown (CPU/RAM ritornano sotto soglia).

## Dipendenze
- Issue 001 (schema config)
- Issue 004 (k6 host setup)
- Issue 005 (queries Prometheus)

