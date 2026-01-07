# DFaaS Plugin Refactoring: Global Setup & Direct Execution

## Obiettivo
Ottimizzare il plugin DFaaS per migliorare performance, stabilità e supporto multi-target, disaccoppiando il provisioning dell'infrastruttura dall'esecuzione dei benchmark.

## Architettura Corrente (Problemi)
1.  **Overhead Ansible**: `K6Runner` invoca `ansible-playbook` per *ogni singola iterazione* di test (21+ volte per benchmark). Questo introduce una latenza enorme (5-10s overhead per test).
2.  **Conflitti di Setup**: Ogni runner (su ogni target) prova a eseguire il playbook di setup (`setup_k6.yml`) sulla stessa macchina generatore condivisa, rischiando conflitti di lock APT/DPKG.
3.  **Logging Oscuro**: Gli errori di esecuzione remota sono mascherati dall'output di Ansible.

## Nuova Architettura Proposta

### 1. Global Setup (Controller-Driven)
Spostare la responsabilità dell'installazione di k6 dal livello "Runner Locale" al livello "Controller Globale".

*   **Chi**: Il Controller (`lb run`).
*   **Quando**: Fase di Setup Globale (prima di lanciare i runner).
*   **Come**:
    *   Il plugin DFaaS espone un playbook `setup.yml` (già esistente, ma va potenziato).
    *   Questo playbook leggerà l'indirizzo `k6_host` dalla configurazione del plugin.
    *   Aggiungerà dinamicamente questo host all'inventario in memoria (`add_host`).
    *   Eseguirà i task di installazione k6 su questo host.
*   **Risultato**: Quando i runner partono, la macchina generatore è già pronta, aggiornata e configurata. Nessuna race condition.

### 2. Direct Execution (Fabric/SSH)
Sostituire l'uso di Ansible nel loop di test con connessioni SSH dirette gestite da Python.

*   **Chi**: `K6Runner` (in esecuzione sul Target).
*   **Cosa**:
    *   Usa la libreria `fabric` (o `paramiko` via fabric) per connettersi al Generatore.
    *   Crea un workspace remoto univoco per l'iterazione (`mkdir -p ...`).
    *   Trasferisce i file di configurazione (`scp`).
    *   Lancia k6 (`ssh k6 run ...`).
    *   Scarica i risultati.
*   **Vantaggi**:
    *   Zero overhead di avvio.
    *   Controllo granulare su timeout e segnali.
    *   Log leggibili direttamente dallo stdout/stderr.

## Piano di Implementazione

### Fase A: Preparazione Controller & Setup
1.  **Modifica `lb_plugins/plugins/dfaas/ansible/setup.yml`**:
    *   Attualmente questo file configura il *target* (login faas-cli, etc).
    *   Va esteso (o creato un `setup_global.yml`) per includere la logica di provisioning del *generatore*.
    *   Deve usare `add_host` per includere `k6_host` nel play.
    *   Deve importare i task da `setup_k6.yml` applicandoli al gruppo dinamico del generatore.

### Fase B: Refactoring K6Runner (Fabric)
1.  **Dipendenze**: Aggiungere `fabric` al progetto.
2.  **Modifica `lb_plugins/plugins/dfaas/services/k6_runner.py`**:
    *   Rimuovere il metodo `execute` basato su `subprocess(ansible)`.
    *   Implementare `_ssh_conn()` che restituisce una connessione Fabric riutilizzabile o nuova.
    *   Implementare `execute` usando `conn.run()` e `conn.put()`.
    *   Implementare la gestione del workspace remoto univoco (`/tmp/dfaas-runs/{uuid}`).

### Fase C: Pulizia DfaasGenerator
1.  **Rimuovere Setup**: `DfaasGenerator` non deve più preoccuparsi di lanciare `setup_k6.yml`. Assume che l'ambiente sia pronto.
2.  **Semplificazione**: Rimuovere la logica di streaming log SSH parallelo, dato che ora possiamo leggere lo stream direttamente dal comando di esecuzione.

## Dettagli Tecnici

### Gestione Multi-Target
Poiché il setup è globale e unico, non ci sono conflitti di installazione.
Poiché l'esecuzione usa workspace univoci (UUID), non ci sono conflitti sui file di configurazione.
Il carico concorrente (CPU/Rete) sul generatore rimane responsabilità dell'utente (dimensionamento).

### Dipendenze
*   `fabric`: Richiesta per il runner.

## Timeline
1.  [x] Aggiunta `fabric` (`uv add fabric`).
2.  [x] Implementazione Setup Globale (Playbook).
3.  [x] Refactoring `K6Runner`.
4.  [x] Pulizia (Rimozione `run_k6.yml`).
5.  Test End-to-End.
