# Issue: Documentazione DFaaS plugin (runbook + troubleshooting)

## Contesto
Serve una guida operativa completa per usare il plugin DFaaS con k3s/OpenFaaS e k6 su host separato.

## Obiettivo
Produrre documentazione dettagliata in repo (nuovo documento) con:
- architettura host (target vs k6-host)
- prerequisiti
- esempio config
- flusso di esecuzione
- troubleshooting

## Contenuti richiesti
### Architettura
- Target host: runner + k3s + OpenFaaS + Prometheus.
- k6-host: esecuzione carico, controllato dal runner.
- Comunicazioni:
  - runner -> k6-host via SSH
  - k6-host -> gateway OpenFaaS (HTTP)
  - runner -> Prometheus (HTTP)

### Prerequisiti
- Accesso SSH dal target al k6-host.
- Porte: 31112 (OpenFaaS gateway), 9090 (Prometheus), 22 (SSH).
- Pacchetti: curl, jq, kubectl, faas-cli, ansible (sul runner).

### Configurazione
- Esempio YAML completo (schema issue 001).
- Spiegazione campi (k6_host, functions, rates, combinations, overload, cooldown).

### Flusso di esecuzione
- Setup target host (k3s/OpenFaaS/Prometheus).
- Setup k6-host (k6).
- Run: una config per volta, cooldown, skip dominanti.
- Output: dove leggere CSV e summary.

### Troubleshooting
- OpenFaaS gateway non raggiungibile.
- Prometheus non raggiungibile.
- k6 fallisce per timeout.
- Cooldown non rientra (CPU/RAM sempre alta).

## Task dettagliati
- [ ] Creare doc `docs/dfaas_plugin.md` (o path concordato).
- [ ] Inserire diagramma testuale host/porte.
- [ ] Aggiungere sezione FAQ con errori comuni.

## Acceptance criteria
- Doc completo con esempi e passi riproducibili.
- Nessuna dipendenza su knowledge esterna non documentata.

