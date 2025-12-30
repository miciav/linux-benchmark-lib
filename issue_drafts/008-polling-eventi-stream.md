# Issue: Task di polling per eventi LB_EVENT dal file remoto

## Contesto
Con LocalRunner in background serve un meccanismo che legga incrementalmente il file eventi e trasformi ogni riga `LB_EVENT` in output Ansible, così il callback `lb_events` possa inoltrarla al controller.

## Obiettivo
Implementare una serie di task brevi che:
- leggono solo le nuove righe del file eventi (offset),
- emettono le righe via `debug`/`stdout`,
- terminano quando trovano la sentinella di completamento (es. `status=done`).

## Scope
- Nuovo task file (es. `tail_lb_events.yml`) richiamato in loop.
- Gestione offset per host (fact persistente tra iterazioni).
- Condizione di uscita: riga `LB_EVENT` con `status=done` o `status=failed` per la ripetizione corrente.

## Non-scope
- Avvio async del runner (issue 007).
- Stop/teardown (issue 009).

## Task dettagliati
- [ ] Introdurre variabile `lb_event_offset` per host (bytes letti).
- [ ] Task che legge `lb_events.stream.log` da offset (es. `tail -c +N`).
- [ ] Per ogni riga nuova: `debug`/`stdout` con la riga completa `LB_EVENT ...`.
- [ ] Aggiornare offset a fine task.
- [ ] Loop con `retries/delay` per evitare busy loop.
- [ ] Terminare loop quando la riga contiene la sentinella per la ripetizione corrente.

## Acceptance criteria
- Gli eventi compaiono nel log stream durante l'esecuzione della ripetizione.
- Il polling termina automaticamente quando la ripetizione è completata o fallita.

## Test plan (design-level)
- Simulare un file eventi con righe incrementalmente aggiunte e verificare che le righe vengano emesse una sola volta.
- Verificare che il loop si arresti su `status=done`.

## Dipendenze
- Issue 007 per la creazione del file eventi.
- Questa soluzione richiede modifiche a playbook/runner fuori dal plugin DFaaS.
