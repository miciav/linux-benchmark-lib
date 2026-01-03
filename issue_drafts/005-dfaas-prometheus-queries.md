# Issue: Prometheus queries (queries.yml) + raccolta metriche legacy

## Contesto
Il plugin DFaaS deve raccogliere metriche Prometheus come in `metrics_predictions/samples_generator/utils.py`. Le query devono essere configurabili via `queries.yml` nel plugin.

## Obiettivo
- Definire `queries.yml` con le stesse query legacy.
- Implementare runner di query che supporta range query e instant query.
- Salvare risultati per config/iterazione in CSV.

## Design dettagliato
### Schema `queries.yml`
Proposta (YAML):
```
queries:
  - name: cpu_usage_node
    query: '100 * sum(1 - rate(node_cpu_seconds_total{mode="idle"}[{time_span}]))'
    range: true
    step: '10s'

  - name: ram_usage_node
    query: 'avg(avg_over_time(node_memory_MemTotal_bytes[{time_span}]) - avg_over_time(node_memory_MemAvailable_bytes[{time_span}]))'
    range: true
    step: '10s'

  - name: ram_usage_node_pct
    query: '100 * avg(1 - ((avg_over_time(node_memory_MemFree_bytes[{time_span}]) + avg_over_time(node_memory_Cached_bytes[{time_span}]) + avg_over_time(node_memory_Buffers_bytes[{time_span}])) / avg_over_time(node_memory_MemTotal_bytes[{time_span}])))'
    range: true
    step: '10s'

  - name: power_usage_node
    query: 'avg_over_time(scaph_host_power_microwatts[{time_span}])'
    range: true
    step: '10s'
    enabled_if: scaphandre

  - name: ram_usage_function
    query: 'avg_over_time(container_memory_usage_bytes{id=~"^/kubepods.*", container_label_io_kubernetes_container_name="{function_name}"}[{time_span}])'
    range: true
    step: '10s'

  - name: cpu_usage_function
    query: '100 * sum(rate(container_cpu_usage_seconds_total{id=~"^/kubepods.*", container_label_io_kubernetes_container_name="{function_name}"}[{time_span}]))'
    range: true
    step: '10s'

  - name: power_usage_function
    query: 'sum(avg_over_time(scaph_process_power_consumption_microwatts{pid=~"{pid_regex}"}[{time_span}]))'
    range: true
    step: '10s'
    enabled_if: scaphandre
```

### Placeholder support
- `{time_span}` viene sostituito con la durata config (es: `30s`).
- `{function_name}` per metriche per funzione.
- `{pid_regex}` per scaphandre (se supportato).

### Esecuzione query
- Se `start_time` e `end_time` disponibili: usare `/api/v1/query_range`.
- Se non disponibili: usare `/api/v1/query` (instant).
- Estrarre media su tutti i punti (legacy: `get_avg_value_from_response`).
- Gestire timeout e retry (legacy: retry 30s).

### Output
- CSV per config/iterazione con colonne:
  - `cpu_usage_node`, `ram_usage_node`, `ram_usage_node_pct`, `power_usage_node`
  - `cpu_usage_function_<name>`, `ram_usage_function_<name>`, `power_usage_function_<name>`
- `power_usage_*` = NaN se scaphandre disabilitato.

## Task dettagliati
- [ ] Creare `lb_plugins/plugins/dfaas/queries.yml` con le query legacy.
- [ ] Implementare loader YAML con placeholder substitution.
- [ ] Implementare query runner (range/instant) con retry.
- [ ] Integrare con generator per scrivere CSV per config.

## Acceptance criteria
- Query set identico a legacy.
- CSV metriche per ogni config/iterazione.
- Errori Prometheus gestiti con retry.

## Test plan
- Test manuale: query node CPU/RAM su cluster k3s.
- Test per funzioni: verificare metriche per almeno una funzione deployata.

## Dipendenze
- Issue 002 (generator chiama query runner)
- Issue 003 (Prometheus/exporters installati)

