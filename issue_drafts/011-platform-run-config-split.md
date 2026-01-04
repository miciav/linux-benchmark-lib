# Issue: Separazione Platform config vs Run config

## Contesto
Oggi `BenchmarkConfig` miscela impostazioni di piattaforma e run, inclusi workload `enabled` e `plugin_settings`. Questo crea ambiguita: la stessa config puo essere sia profilo di piattaforma sia config di run. Serve separare nettamente le responsabilita.

Decisioni concordate:
- Platform config in `~/.config/lb/platform.json`.
- Platform config puo contenere Loki, output defaults, controller defaults, ecc.
- In platform config la sezione plugin contiene solo enable/disable:
  `"plugins": { "dfaas": true, "fio": false }`.
- Run config contiene `remote_hosts` e workload da eseguire.
- Nel run config non esiste `enabled`; la presenza del workload implica esecuzione.
- Se un workload e presente nel run config ma e disabilitato nel platform config:
  warning e skip nel run plan (non esecuzione).
- Nessuna info di provisioning nel platform config (scelta solo via CLI).

## Obiettivo
Separare i due livelli di configurazione con merge rules chiare e un comportamento prevedibile in CLI e run plan.

## Scope
- Nuovo modello Platform config (es. `PlatformConfig`).
- File path fisso `~/.config/lb/platform.json`.
- Merge rules tra Platform config e Run config (solo lettura; no esecuzione dai dati platform).
- Enforce skip se plugin disabilitato nel platform config.
- Run plan segnala `skipped (disabled by platform)`.
- Documentazione aggiornata.

## Non-scope
- Cambiare il provisioning (multipass/docker/remote) o spostarlo nel platform config.
- Cambiare la semantica dei plugin stessi.
- Migrazioni automatiche che modificano i file di run (solo parsing/merge).

## Proposta di struttura
### Platform config (`~/.config/lb/platform.json`)
```
{
  "plugins": { "dfaas": true, "fio": false },
  "loki": { "enabled": true, "endpoint": "http://<controller-ip>:3100" },
  "output_dir": "./benchmark_results",
  "report_dir": "./reports",
  "data_export_dir": "./data_exports"
}
```

### Run config (file passed via `-c`)
```
{
  "remote_hosts": [ ... ],
  "workloads": {
    "dfaas": { "plugin": "dfaas", "options": { ... } },
    "fio": { "plugin": "fio", "options": { ... } }
  }
}
```

## Task dettagliati
- [ ] Definire `PlatformConfig` (Pydantic) con campi ammessi e `plugins` map.
- [ ] Nuovo loader per `~/.config/lb/platform.json` con default vuoto.
- [ ] Integrare la piattaforma nel `ConfigService` (load/resolve non-bloccanti).
- [ ] Definire merge rules (Platform + Run) senza sovrascrivere i workload del run.
- [ ] Validazione: se workload presente e plugin disabled -> warning + skip.
- [ ] Aggiornare `run_plan` per mostrare `skipped (disabled by platform)`.
- [ ] Aggiornare `lb config ...` o aggiungere `lb platform ...` per edit/list.
- [ ] Aggiornare docs: `docs/configuration.md` e `docs/cli.md`.
- [ ] Aggiornare tests: unit per merge + plan skip + config resolution.

## Acceptance criteria
- Il run config contiene solo workload da eseguire e nessun `enabled`.
- Platform config non guida mai l'esecuzione; solo filtra/limita via enable/disable.
- Se un workload e disabilitato in platform config, il run plan lo segnala come skipped.
- Breaking change: nessuna compatibilita con i vecchi run config.
  I run config legacy devono essere aggiornati al nuovo schema.

## Test plan (design-level)
- Unit test: merge Platform+Run config con plugin disabled.
- Unit test: run plan segnala skipped.
- CLI test: `lb config` continua a funzionare con run config.
- E2E: run config con workload disabilitato -> non eseguito.

## Rischi / Note
- Cambio breaking: i vecchi run config con `enabled` o plugin non ammessi
  vanno corretti manualmente.
- Necessita di comunicare chiaramente la separazione nei docs.
