# Issue: Stop coordinato per runner async + teardown workload/globale

## Contesto
Con runner async e polling, un doppio Ctrl+C deve fermare sia il loop di polling sia il LocalRunner, e avviare i teardown (workload + globale) senza lasciare processi orfani.

## Obiettivo
Gestire lo stop in modo deterministico:
- interrompere i task di polling,
- fermare il job async del runner (graceful e poi hard kill),
- eseguire teardown workload e globale.

## Scope
- Integrazione stop token/STOP file nel flow Ansible.
- Task di terminazione del job async (check + kill).
- Garanzia di esecuzione dei teardown anche in caso di stop.

## Non-scope
- Dettagli di emissione eventi (issue 008).

## Task dettagliati
- [ ] Creare file STOP sul target quando il controller arma lo stop.
- [ ] Fare in modo che il polling verifichi lo stop e termini subito.
- [ ] Verificare stato job async via `async_status`.
- [ ] Se ancora running dopo timeout: kill del processo.
- [ ] Eseguire teardown workload e teardown globale in ogni caso (success/stop/fail).

## Acceptance criteria
- Dopo stop, il runner non rimane in esecuzione sul target.
- I teardown vengono eseguiti e non si resta in `stop_failed`.

## Test plan (design-level)
- Avviare una ripetizione lunga, inviare stop, verificare:
  - polling interrotto,
  - job async terminato,
  - teardown eseguiti.

## Dipendenze
- Issue 007 e 008.
- Richiede modifiche a playbook/controller fuori dal plugin DFaaS.
