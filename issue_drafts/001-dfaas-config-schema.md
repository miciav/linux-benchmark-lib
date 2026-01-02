# Issue: Definire schema config DFaaS + regole combinazioni/cooldown/dominanza

## Contesto
Dobbiamo migrare la logica di `metrics_predictions/samples_generator` in un plugin DFaaS per linux-benchmark-lib, senza modificare il core. La configurazione deve essere leggibile da file e sovrascrivibile con `options` (user_defined). Il generatore lavorera una configurazione per volta, applicando cooldown e skip delle configurazioni dominanti in overload.

## Obiettivo
Definire lo schema di configurazione del plugin DFaaS (YAML/JSON) e formalizzare le regole:
- combinazioni funzioni e liste di rate
- cooldown (stesse condizioni legacy)
- overload (stesse condizioni legacy)
- dominanza (nuova definizione per rate per funzione)

## Scope
- Schema completo con default e vincoli.
- Merge tra file config (common + plugins.dfaas) e override via `options`.
- Regole di generazione delle configurazioni e di skip.

## Non-scope
- Implementazione del plugin o playbook (in altre issue).

## Schema proposto (YAML)
```
common:
  timeout_buffer: 10

plugins:
  dfaas:
    k6_host: "10.0.0.50"
    k6_user: "ubuntu"
    k6_ssh_key: "~/.ssh/id_rsa"
    k6_port: 22

    gateway_url: "http://<target-ip>:31112"
    prometheus_url: "http://<target-ip>:9090"

    functions:
      - name: "figlet"
        method: "POST"
        body: "Hello DFaaS!"
        headers:
          Content-Type: "text/plain"
      - name: "eat-memory"
        method: "GET"
        body: ""

    rates:
      min_rate: 0
      max_rate: 200
      step: 10

    combinations:
      min_functions: 1
      max_functions: 2

    duration: "30s"
    iterations: 3

    cooldown:
      max_wait_seconds: 180
      sleep_step_seconds: 5
      idle_threshold_pct: 15

    overload:
      cpu_overload_pct_of_capacity: 80
      ram_overload_pct: 90
      success_rate_node_min: 0.95
      success_rate_function_min: 0.90
      replicas_overload_threshold: 15

    queries_path: "lb_plugins/plugins/dfaas/queries.yml"
    deploy_functions: true
```

## Regole formali
### Generazione rate list
- `rates = [min_rate..max_rate step]` inclusivi.
- Ordinati in ordine crescente (legacy: generati decrescenti e poi `sort`).

### Combinazioni funzioni
- Prendere `min_functions..max_functions` (max escluso) come in legacy.
- Generare tutte le combinazioni di nomi funzioni.

### Configurazione di carico
- Per ogni set di funzioni, creare il prodotto cartesiano dei rate per funzione.
- Ogni configurazione e una tupla `(function, rate)` per ciascuna funzione.

### Dominanza (nuova definizione)
- Config B domina A se, per tutte le funzioni: `rate_B >= rate_A` e per almeno una funzione `rate_B > rate_A`.
- Se una config A e marcata overload, tutte le config successive che la dominano vanno skippate.

### Cooldown (legacy)
- Prima di ogni iterazione, attendere finche:
  - CPU, RAM, POWER entro `idle + idle * idle_threshold_pct/100`
  - repliche per funzione < 2
- Attesa massima `max_wait_seconds`, altrimenti abort.

### Overload (legacy)
- Un nodo e overload se:
  - avg success rate < `success_rate_node_min` **oppure**
  - CPU > `cpu_overload_pct_of_capacity` **oppure**
  - RAM > `ram_overload_pct` **oppure**
  - almeno una funzione overload
- Una funzione e overload se:
  - success rate < `success_rate_function_min` **oppure**
  - replicas >= `replicas_overload_threshold`

## Task dettagliati
- [ ] Definire Pydantic model `DfaasConfig` con validazioni (rate step, min/max, duration, iterations > 0).
- [ ] Specificare merge: `config_path` (common + plugins.dfaas) -> config base; `options` override.
- [ ] Definire formato `functions` con payload/headers come in `samples_generator/utils.py`.
- [ ] Aggiungere esempio config completo in docs del plugin.

## Acceptance criteria
- Schema completo documentato con default e vincoli.
- Esempio config valido che copre tutti i campi.
- Regole di dominanza/cooldown/overload descritte e formalizzate.

## Test plan (design-level)
- Verifica manuale con configurazioni note (1-2 funzioni) e rate list piccole.
- Validazione che dominanza e cooldown coincidono con legacy.

## Dipendenze
- Issue 002 (generator) usere questo schema.

