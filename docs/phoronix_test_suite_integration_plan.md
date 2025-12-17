# Piano di integrazione: Phoronix Test Suite (PTS) come “virtual plugin bundle”

## Executive summary (cosa vogliamo ottenere, in pratica)
Vogliamo integrare `phoronix-test-suite` (PTS) in modo che:

- PTS venga installato **una sola volta** (per host), usando il `.deb` incluso nel plugin.
- Ogni PTS test-profile selezionato appaia come **workload plugin separato** (es. `pts_build_linux_kernel`, `pts_compress_7zip`).
- Aggiungere un nuovo workload richieda **solo** aggiungere il nome del profile a **un file di configurazione** (YAML), senza toccare codice.
- Setup/install dei profili e run siano automatizzabili sia in locale sia in remoto, coerenti con il flusso attuale (Ansible setup + `LocalRunner`).

Questa scelta è intenzionale: massimizza compatibilità con UI/config/runner e riduce il costo di manutenzione (non “inventiamo” un nuovo modello di workload, lo mappiamo sul modello esistente).

---

## Obiettivi / Non-obiettivi

### Obiettivi
- Esporre N profili PTS come N istanze `WorkloadPlugin`.
- Aggiungere profili tramite file YAML (modalità “minima”: solo nomi).
- Provisioning idempotente (install PTS + install profilo) in fase di setup, senza ripetizioni inutili.
- Esecuzione non-interattiva o fallimento con messaggio chiaro (no prompt “bloccanti”).
- Artifacts e risultati PTS acquisiti in output per-run/per-workload, in modo tracciabile.

### Non-obiettivi (per evitare scope creep)
- Non scrivere un parser completo di tutti i formati PTS “out of the box” al day-1.
- Non supportare tutti i sistemi operativi: target primario Debian/Ubuntu (perché `.deb` + apt).
- Non rendere offline l’install dei profili: PTS tipicamente scarica contenuti; questo è un vincolo esterno.

---

## Assunzioni chiave (per “andare a botta sicura”)
- In modalità remote/multipass, l’Ansible global setup copia il repo in `/opt/lb` (`lb_controller/ansible/playbooks/setup.yml`), quindi:
  - il `.deb` incluso nel plugin è disponibile anche sul target,
  - il file YAML dei workload è disponibile anche sul target.
- La modalità `lb run` locale usa `SetupService` per eseguire i playbook anche su localhost (con `become: true`), quindi possiamo installare PTS via Ansible anche in locale (se sudo è disponibile).
- PTS genera risultati sotto una directory “home” (tipicamente `~/.phoronix-test-suite/...`). Non assumiamo che PTS esponga sempre un export JSON stabile: lo gestiamo per step.

---

## Stato attuale (architettura plugin) e gap
Oggi il sistema carica plugin workload da moduli che esportano `PLUGIN` (singolo oggetto):
- Built-in: `lb_runner/plugin_system/builtin.py`
- User plugins: `lb_runner/plugin_system/registry.py`

**Gap**: un modulo non può esporre più workload plugin. Per PTS serve un “bundle” che materializzi N plugin da una lista configurabile.

---

## Design proposto (preciso e mantenibile)

### A) Estensione discovery: supporto multi-export
Estendere discovery/registry per supportare questi export (priorità in ordine):
1. `get_plugins() -> list[WorkloadPlugin]` (consigliato: rilegge config e costruisce la lista ogni volta che si crea un registry)
2. `PLUGINS: list[WorkloadPlugin]` (utile se lista statica)
3. `PLUGIN: WorkloadPlugin` (compatibilità con plugin esistenti)

**Definition of done**
- Un modulo con `get_plugins()` viene scoperto e registra N plugin.
- I plugin legacy con `PLUGIN` continuano a funzionare invariati.
- Test unit copre i 3 casi (get_plugins, PLUGINS, PLUGIN).

### B) Plugin PTS built-in (bundle) guidato da config file
Creare un plugin built-in in `lb_runner/plugins/phoronix_test_suite/` che:
- carica un file YAML di configurazione (vedi sezione “Config file”),
- genera N `WorkloadPlugin` (uno per profile),
- per ogni plugin fornisce:
  - `name` stabile (derivato dal profile o override),
  - `description`/`tags` (default o override),
  - `config_cls` comune (`PhoronixConfig`),
  - `create_generator()` che esegue `phoronix-test-suite benchmark <profile>`.

### C) Setup/Teardown: idempotenza e “install once”
Requisito: “PTS va installato una volta” + “ogni profilo va installato (setup) prima del run”.

Approccio robusto:
- Installazione PTS e profilo avvengono in **workload setup** (Ansible), che già esiste in locale e remoto.
- La logica è idempotente: se PTS/profilo sono già presenti, il setup diventa un no-op.

Problema architetturale da risolvere (necessario per aggiungere profili solo via config):
- Un playbook generico di setup PTS deve sapere *quale profile installare* per il workload corrente.
- Oggi `SetupService.provision_workload()` e `BenchmarkController` non passano extravars “per-plugin” al playbook.

Soluzione strutturale (minima, generalizzabile, mantenibile):
- Aggiungere al contratto plugin due metodi non-abstract con default `{}`:
  - `get_ansible_setup_extravars() -> dict[str, Any]`
  - `get_ansible_teardown_extravars() -> dict[str, Any]`
- Modificare:
  - `lb_controller/services/setup_service.py` per passare `extravars` al playbook,
  - `lb_controller/controller.py` per unire `extravars` globali + extravars del plugin.

In questo modo:
- tutti i plugin esistenti restano compatibili (default `{}`),
- il plugin PTS può usare **un solo** playbook generico e passare `pts_profile=<profile>`,
- aggiungere un profile nel YAML è sufficiente: il plugin generato porta con sé `pts_profile` nel setup.

---

## Config file (il punto chiave: aggiungere workload senza toccare codice)

### Posizione del file (scelta operativa)
Per rispettare “aggiungo un workload modificando solo un file”, fissiamo una posizione *nel repo* (copiata anche su host remoti):
- `lb_runner/plugins/phoronix_test_suite/pts_workloads.yaml`

Opzionale (fallback futuro): supportare override con env `LB_PTS_WORKLOADS_FILE`, ma non è necessario per il primo giro.

### Schema YAML (v1)
```yaml
version: 1

pts:
  deb_path: "lb_runner/plugins/phoronix_test_suite/assets/phoronix-test-suite_10.8.4_all.deb"
  apt_packages: ["gdebi-core", "unzip"]
  binary: "phoronix-test-suite"

  # Dove PTS salva profili/cache/risultati.
  # Usiamo `PTS_USER_PATH_OVERRIDE` (non `HOME`) perché PTS calcola la sua user-path
  # internamente; il path deve finire con "/" perché PTS concatena stringhe.
  home_root: "/opt/lb/.phoronix-test-suite/"

workloads:
  # Modalità minima (raccomandata): basta aggiungere il nome del profile PTS
  - build-linux-kernel
  - compress-7zip

  # Modalità estesa (opzionale): override di naming/metadata e parametri PTS
  - profile: fio
    plugin_name: pts_fio
    description: "FIO via PTS"
    tags: ["storage", "io"]
    args: []
```

### Regole di mapping (deterministiche)
- Se `workloads` contiene una stringa `build-linux-kernel`:
  - `profile = "build-linux-kernel"`
  - `plugin_name = "pts_build_linux_kernel"` (lowercase, `-`→`_`, prefisso `pts_`)
- Se `plugin_name` è specificato nella forma estesa, viene usato così com’è.
- Duplicati:
  - Se due entry producono lo stesso `plugin_name`, è errore (fail-fast in discovery, messaggio chiaro).

### Operatività (come verifico che “funziona”)
- Dopo aver aggiunto un nome al file YAML:
  - `lb plugins` deve mostrare il nuovo plugin.
  - Il run deve poter referenziare il nuovo plugin in `BenchmarkConfig.workloads`.

Nota su caching:
- `lb_controller/services/plugin_service.create_registry()` cachea il registry; per vedere modifiche nel medesimo processo serve `refresh=True` (o riavvio). In CLI tipicamente si rilancia il comando, quindi è ok.

---

## Packaging: `.deb` nel plugin (come richiesto)

### Asset
- Inserire il `.deb` in:
  - `lb_runner/plugins/phoronix_test_suite/assets/phoronix-test-suite_10.8.4_all.deb`
- URL di riferimento:
  - `https://phoronix-test-suite.com/releases/repo/pts.debian/files/phoronix-test-suite_10.8.4_all.deb`

Nota (importante per “andare a botta sicura”):
- Verificare condizioni di ridistribuzione/licenza del `.deb`. Se emergono vincoli, fallback: download in setup (richiede network).

---

## Setup PTS e profili (Ansible) — dettagli implementativi

### Prerequisiti (Debian/Ubuntu)
- `sudo apt install gdebi-core unzip`
- Install PTS:
  - `sudo gdebi -n <path_al_deb>`

### Playbook di setup PTS (generico)
Percorso consigliato:
- `lb_runner/plugins/phoronix_test_suite/ansible/setup.yml`

Variabili richieste (da extravars plugin):
- `pts_profile`: es. `build-linux-kernel`
- `pts_deb_relpath`: percorso relativo al `.deb` (default dal YAML)
- `pts_home_root`: directory usata come `PTS_USER_PATH_OVERRIDE` (default dal YAML, deve finire con `/`)

Idempotenza (come la rendiamo “sicura”):
- PTS install:
  - check `command -v phoronix-test-suite` (se presente, skip install deb)
- Batch setup (necessario per usare `batch-benchmark` senza prompt):
  - eseguire `phoronix-test-suite batch-setup` in modo non-interattivo (risposte predefinite “sicure”: niente upload risultati, niente prompt)
- Profile install:
  - eseguire `phoronix-test-suite install <profile>` con `PTS_USER_PATH_OVERRIDE={{ pts_home_root }}`
  - se PTS è idempotente, l’operazione si conclude rapidamente quando già installato;
  - opzionale: aggiungere un check su directory `{{ pts_home_root }}/test-profiles/pts/{{ pts_profile }}` (se presente, skip) — da confermare empiricamente.

### Teardown
Per default, nessun teardown distruttivo:
- non rimuoviamo PTS,
- non rimuoviamo cache profili,
perché ridurrebbe riproducibilità e aumenterebbe tempi di run.

Se serve un teardown “pulizia”, lo rendiamo opt-in (flag in `PhoronixConfig`), e il playbook può rimuovere solo artifacts temporanei per-run.

---

## Run workload PTS (generator) — dettagli implementativi

### Comando base
- Esecuzione:
  - `phoronix-test-suite benchmark <profile>`

### Non-interattività
PTS può generare prompt. Il piano è:
1. Eseguire `phoronix-test-suite batch-setup` (una volta) per impostare `BatchMode/Configured=TRUE` e disabilitare prompt/upload.
2. Usare comandi “batch” (`batch-install`, `batch-benchmark`) per evitare qualsiasi interazione.
3. Se batch mode non è configurabile, fallire con messaggio chiaro (senza blocchi silenziosi).

### User-path controllata e raccolta risultati (robustezza senza “magia”)
Per evitare di dipendere da path impliciti:
- il generator esegue PTS con `PTS_USER_PATH_OVERRIDE=<pts_home_root>` (coerente col setup) così profili e risultati finiscono nello stesso albero controllato.
- dopo l’esecuzione, per acquisire il result-dir “giusto” senza affidarsi al parsing di stdout:
  1. listare le directory presenti in `<pts_home_root>/test-results` prima del run,
  2. rieseguire la lista dopo il run,
  3. calcolare il delta; se >1, scegliere la più recente per mtime.
- copiare la result dir selezionata dentro `workload_output_dir` (es. `.../<workload>/pts_result/`).

Questa strategia è deterministica e funziona anche se PTS cambia format di output.

### Dipendenze di sistema (workaround Debian)
PTS può provare a installare dipendenze via script interni di distro-detection.
Su Debian 13 (trixie) PTS 10.8.4 usa uno script che esegue `apt-get update $*` (errore: “The update command takes no arguments”).
Per evitare fallimenti, pre-installiamo le dipendenze tramite `apt-get` (lista `apt_packages` nel YAML) prima di invocare PTS.

---

## Visibilità output (incluso teardown)
Sì: l’output di teardown si vede quando lo stream UI è attivo (remote/multipass e anche local in run_service).
- In run UI viene salvato in `benchmark_results/<run_id>/ui_stream.log`.
- Per output Ansible raw (più verboso) usare `lb run --debug`.

---

## Layout file (concreto)
```
lb_runner/plugins/phoronix_test_suite/
  plugin.py                     # provider: get_plugins() → [WorkloadPlugin...]
  pts_workloads.yaml            # file che l’utente modifica per aggiungere profili
  assets/
    phoronix-test-suite_10.8.4_all.deb
  ansible/
    setup.yml                   # playbook generico (usa pts_profile via extravars)
    teardown.yml                # opzionale / no-op
```

---

## Strategia test (CI-friendly, mirata)

### Unit test (obbligatori)
- Discovery multi-export:
  - `get_plugins()` registra N plugin
  - `PLUGINS` registra N plugin
  - `PLUGIN` registra 1 plugin
- Parser YAML PTS:
  - string list → mapping deterministico a `plugin_name`
  - dup `plugin_name` → errore
  - validazione campi base (`version`, `pts.deb_path`, `workloads`)
- Merging extravars:
  - SetupService/Controller uniscono extravars globali + plugin.

### Integration test (opzionali, skip-safe)
- Skip se `phoronix-test-suite` non è disponibile (o se non Linux).
- Se presente, testare `compress-7zip` come smoke (tendenzialmente più leggero di kernel build).

---

## Roadmap con deliverable chiari

### Milestone 1 — Multi-export + test
- Implementare supporto `get_plugins`/`PLUGINS` in `builtin.py` e `registry.py`.
- Test unit in `tests/unit/common/test_plugin_registry.py`.

### Milestone 2 — Contract extravars per setup/teardown
- Aggiungere metodi default a `WorkloadPlugin`:
  - `get_ansible_setup_extravars()`
  - `get_ansible_teardown_extravars()`
- Passare extravars in:
  - `lb_controller/services/setup_service.py`
  - `lb_controller/controller.py`
- Test unit su merge extravars (minimo).

### Milestone 3 — Plugin PTS + config file + 2 workload iniziali
- Aggiungere directory plugin `lb_runner/plugins/phoronix_test_suite/`.
- Inserire `.deb` e `pts_workloads.yaml` con:
  - `build-linux-kernel`
  - `compress-7zip`
- Implementare provider `get_plugins()` che legge YAML e genera plugin.
- Implementare generator che esegue `phoronix-test-suite benchmark <profile>`.

### Milestone 4 — Setup Ansible PTS idempotente
- Implementare `ansible/setup.yml` con:
  - install `gdebi-core`, `unzip`,
  - install `.deb` se PTS mancante,
  - install profilo `pts_profile`.
- Verificare che output setup/teardown appaia nello stream.

### Milestone 5 — Risultati e artifacts robusti
- Implementare la strategia “diff test-results dir” e copia result-dir nel workload output.
- Export minimo: salvare stdout/stderr e path result-dir nel `generator_result`.

---

## Rischi e mitigazioni
- PTS interattivo: mitigazione con batch mode, altrimenti fail-fast e docs.
- Dimensione `.deb` e licenza: mitigazione con checksum + alternativa download (se consentito).
- Profilo install lento: mitigazione con caching in `pts_home_root` e setup idempotente.

---

## Procedura operativa: aggiungere un nuovo workload (solo config)
1. Aggiungere il profile a `lb_runner/plugins/phoronix_test_suite/pts_workloads.yaml` (es. `- openssl`).
2. Verificare che compaia come plugin:
   - `lb plugins` → deve apparire `pts_openssl` (o `plugin_name` se specificato).
3. Abilitare ed eseguire come gli altri workload:
   - abilita in config: `lb plugins --enable pts_openssl -c <config>`
   - avvia run: `lb run pts_openssl -c <config>`
