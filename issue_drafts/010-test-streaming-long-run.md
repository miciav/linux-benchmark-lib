# Issue: Test end-to-end per streaming eventi su workload lungo

## Contesto
Serve un test che dimostri che i log `LB_EVENT` arrivano durante una ripetizione lunga (non solo a fine task), validando la soluzione async + polling.

## Obiettivo
Creare un test e2e che:
- avvia una run con durata lunga,
- verifica che eventi compaiano nel log stream prima della fine della run,
- verifica stop/teardown.

## Scope
- Test in `tests/e2e/` o `tests/integration/`.
- Validazione del log stream (es. `ui_stream.log` o file eventi).

## Non-scope
- Implementazione della soluzione async/polling.

## Task dettagliati
- [ ] Preparare config con workload DFaaS lungo (durata > 60s, 1 iterazione).
- [ ] Avviare run in modalità remota (VM o host di test).
- [ ] Attendere la comparsa di almeno un `LB_EVENT` entro una finestra temporale breve (es. 10s).
- [ ] Interrompere la run e verificare teardown + assenza di processi residui.

## Acceptance criteria
- Il test fallisce se i log arrivano solo a fine run.
- Il test passa quando almeno un evento è visibile durante l'esecuzione.

## Test plan (design-level)
- Integrazione con multipass o ambiente CI dedicato.

## Dipendenze
- Issue 007, 008, 009.
