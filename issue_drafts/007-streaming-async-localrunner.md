# Issue: Avvio LocalRunner asincrono + file eventi persistente

## Contesto
Le ripetizioni lunghe bloccano il task Ansible che esegue LocalRunner, quindi lo stdout (LB_EVENT) arriva solo a fine task. Serve separare l'avvio del runner dall'emissione eventi, così il controller può ricevere progressi in tempo quasi reale.

## Obiettivo
Eseguire LocalRunner in background (async) e garantire che LB_EVENT vengano scritti su un file remoto stabile (JSONL o linee `LB_EVENT ...`), per essere letti da task successivi.

## Scope
- Modifica del playbook/ruolo `workload_runner` per avviare LocalRunner con `async: 0` e salvare `job_id`.
- Introduzione di un file eventi per host: `{{ workload_runner_output_dir }}/lb_events.stream.log`.
- Emissione LB_EVENT sul file **oltre** allo stdout, senza perdere l'integrazione con il callback Ansible.

## Non-scope
- Polling dei log o parsing eventi (issue separata).
- Gestione stop/teardown (issue separata).

## Task dettagliati
- [ ] Definire path log eventi remoto (`workload_runner_output_dir/lb_events.stream.log`).
- [ ] Avviare LocalRunner in background con `async: 0` e `poll: 0`.
- [ ] Salvare `job_id` in fact per host.
- [ ] Garantire che LocalRunner scriva LB_EVENT su file (es. `tee` o handler dedicato).
- [ ] Salvare anche `pid`/`cmdline` se utile per stop hard.

## Acceptance criteria
- Il task di avvio runner termina subito e restituisce `job_id`.
- Il file `lb_events.stream.log` esiste e viene aggiornato durante la ripetizione.

## Test plan (design-level)
- Verificare che il job async rimanga in esecuzione dopo il task.
- Verificare che il file eventi contenga righe `LB_EVENT` dopo pochi secondi.

## Dipendenze
- Issue 008 (polling eventi) per la visibilità in dashboard.
- Questa soluzione richiede modifiche a playbook/runner fuori dal plugin DFaaS.
