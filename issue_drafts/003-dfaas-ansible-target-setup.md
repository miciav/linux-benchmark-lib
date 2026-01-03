# Issue: Playbook setup target host (k3s + OpenFaaS + Prometheus + exporters)

## Contesto
Il target host (dove gira il runner) deve essere auto-configurato con k3s, OpenFaaS e stack osservabilita minimale (Prometheus + node-exporter + cAdvisor). Le funzioni devono essere deployate dal catalogo OpenFaaS.

## Obiettivo
Definire playbook Ansible di setup (plugin DFaaS) per installare e configurare:
- k3s
- OpenFaaS
- Prometheus
- node-exporter
- cAdvisor
- funzioni OpenFaaS

## Scope
- Playbook idempotenti.
- Configurazione endpoint accessibili da runner e k6-host.
- Supporto opzionale per Scaphandre (power), se previsto nel config.

## Non-scope
- Implementazione generator k6 (issue 002).

## Design dettagliato
### k3s
- Installazione via script ufficiale (pin versione opzionale).
- Abilitare accesso kubeconfig per l'utente usato da Ansible.
- Verifica: `kubectl get nodes`.

### OpenFaaS
- Installazione via `arkade` o `helm` (scelta coerente con repo).
- Creare namespace `openfaas` e `openfaas-fn`.
- Esposizione gateway (NodePort), porta standard 31112.
- Recuperare password admin via secret e configurare `faas-cli` sul target.

### Prometheus + exporters (stack minimale)
- Applicare manifest YAML per:
  - `node-exporter` DaemonSet + Service
  - `cAdvisor` DaemonSet + Service
  - `prometheus` Deployment + Service + config
- Adattare manifest da `metrics_predictions/infrastructure` a k3s.
- Esporre Prometheus via NodePort (porta 9090).

### Funzioni OpenFaaS
- Deploy da store in base a `functions` config (nomi pubblici).
- Eseguire login `faas-cli` prima del deploy.

### Scaphandre (opzionale)
- Se `scaphandre_enabled=true`, installare e configurare exporter.
- Montare path necessario su host e cluster.

## Task dettagliati
- [ ] Creare playbook `lb_plugins/plugins/dfaas/ansible/setup_target.yml`.
- [ ] Task k3s: install, verify, set kubeconfig.
- [ ] Task OpenFaaS: install, wait rollout, login, expose gateway.
- [ ] Task Prometheus/exporters: apply YAML, restart se necessario.
- [ ] Task deploy funzioni: loop su lista, `faas-cli store deploy`.
- [ ] Task Scaphandre opzionale (flag config).
- [ ] Documentare porte richieste (31112, 9090, 8443, ecc).

## Acceptance criteria
- Playbook idempotente (rerun senza errori).
- Gateway OpenFaaS raggiungibile dal target e dal k6-host.
- Prometheus raggiungibile e query base funzionante.
- Funzioni deployate correttamente.

## Test plan
- Eseguire playbook su VM pulita.
- Verificare `kubectl get pods -n openfaas`.
- Verificare `faas-cli list`.
- Verificare `curl http://<target>:9090/api/v1/query?...`.

## Dipendenze
- Issue 001 (schema config per funzioni)

