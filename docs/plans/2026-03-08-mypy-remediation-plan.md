# Mypy Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** rendere `mypy` un segnale affidabile per il repository e poi ridurre il debito tipologico first-party senza confondere errori di setup, codice vendorizzato e problemi reali del dominio.

**Architecture:** il lavoro va separato in due stream. Prima si corregge il perimetro di analisi di `mypy` e si completa l’ambiente dev con gli stub o con override espliciti per le dipendenze opzionali/non tipizzate. Solo dopo si attacca il debito first-party residuo, partendo dai moduli core che oggi bloccano di più (`lb_app`, `lb_ui`, `lb_controller`, `lb_runner`). Il successo del piano non è “meno rumore”, ma comandi `mypy` riproducibili con failure classificate.

**Tech Stack:** Python 3.12, mypy 1.19.1, uv, pyproject.toml, vendored Ansible callback/collections, strict typing config.

---

## Evidence Snapshot

- Comando documentato: `uv run mypy lb_runner lb_controller lb_app lb_ui`
- Risultato osservato: `263` errori, distribuiti così:
  - `lb_plugins`: `71`
  - `lb_app`: `58`
  - `lb_ui`: `53`
  - `lb_controller`: `38`
  - `lb_runner`: `25`
  - `lb_analytics`: `10`
  - `lb_common`: `7`
  - `lb_provisioner`: `1`
- Questo dimostra che il comando “core” segue gli import e allarga il perimetro.
- Ulteriore rumore:
  - codice vendorizzato sotto `lb_controller/ansible/collections/...`
  - stub mancanti per `pandas`, `yaml`, `psutil`, `seaborn`

## Success Criteria

1. Esiste un comando `mypy` documentato che analizza solo il perimetro dichiarato.
2. Il codice vendorizzato/terze parti embedded non entra più nel check first-party.
3. Le dipendenze dev richieste dal check sono dichiarate oppure ignorate con override espliciti e giustificati.
4. Il debito first-party residuo è inventariato per area, con priorità e batch eseguibili.

### Task 1: Stabilize Mypy Scope

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/contributing.md`

**Step 1: Write the failing verification**

Run:
```bash
uv run mypy lb_runner lb_controller lb_app lb_ui --hide-error-context --no-color-output --no-error-summary
```

Expected: FAIL con errori anche fuori perimetro (`lb_plugins`, `lb_analytics`, `lb_provisioner`, `lb_common`) e dentro codice vendorizzato Ansible.

**Step 2: Write minimal implementation**

- In `pyproject.toml`, aggiungere `exclude` o `[[tool.mypy.overrides]]` per:
  - `lb_controller/ansible/collections/ansible_collections/.*`
  - `__pycache__`
  - eventuali plugin utente/generated che non fanno parte del gate first-party
- Valutare `follow_imports = "skip"` solo per il comando “core”, non come default globale, se serve a far coincidere semantica e documentazione.
- Aggiornare `docs/contributing.md` con il comando realmente supportato e la sua semantica.

**Step 3: Re-run verification**

Run:
```bash
uv run mypy <nuovo-comando-documentato>
```

Expected: gli errori restanti devono appartenere solo al perimetro dichiarato.

### Task 2: Fix Dependency/Stub Mismatch

**Files:**
- Modify: `pyproject.toml`
- Optional: `docs/contributing.md`

**Step 1: Write the failing verification**

Run:
```bash
uv run mypy <comando-core> --hide-error-context --no-color-output --no-error-summary
```

Expected: FAIL con `import-untyped` / `import-not-found` per dipendenze che il repo usa davvero (`pandas`, `yaml`, `psutil`, `seaborn`, `ansible` callback typing, eventuali notifier desktop).

**Step 2: Write minimal implementation**

Scegliere esplicitamente una strategia per ogni dipendenza:

- `pandas`, `PyYAML`, `psutil`, `seaborn`:
  - o aggiungere i relativi stub/dev dependencies;
  - oppure override `ignore_missing_imports = true` per moduli mirati.
- `ansible.plugins.callback` e altri moduli Ansible non tipizzati:
  - override mirato, non `ignore_missing_imports` globale.
- Documentare la scelta nel commento di config, per evitare regressioni future.

**Step 3: Re-run verification**

Run:
```bash
uv run mypy <comando-core>
```

Expected: nessun errore dovuto a pacchetti esterni non tipizzati rimasti fuori policy.

### Task 3: Establish Reliable Commands

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/contributing.md`
- Optional: create `scripts/` helper if useful

**Step 1: Write the failing verification**

Elencare i casi d’uso che oggi si confondono:
- type check “core CI”
- type check “whole repo”
- type check “focused batch”

**Step 2: Write minimal implementation**

Definire comandi distinti e documentati, ad esempio:
- `mypy-core`: gate affidabile per i package core
- `mypy-plugins`: batch dedicato ai workload/plugin
- `mypy-all`: check best-effort dell’intero repo

Se utile, aggiungere script o alias documentati per evitare comandi manuali divergenti.

**Step 3: Re-run verification**

Run tutti i comandi definiti.

Expected:
- `mypy-core` produce solo errori core oppure passa;
- `mypy-plugins` non viene confuso con il gate core;
- `mypy-all` è esplicitamente best-effort finché non si chiude il debito.

### Task 4: Inventory First-Party Typing Debt

**Files:**
- Create: `docs/plans/2026-03-08-mypy-debt-inventory.md`

**Step 1: Gather evidence**

Run:
```bash
uv run mypy <comando-core> --hide-error-context --no-color-output --no-error-summary
```

Raggruppare gli errori per file e categoria.

**Step 2: Write the inventory**

Per ogni file:
- path
- numero errori
- category (`no-untyped-def`, `no-any-return`, `arg-type`, `union-attr`, ecc.)
- root cause presunta
- fix difficulty (`S`, `M`, `L`)
- batch suggerito

**Step 3: Verify usefulness**

Expected: l’inventory permette di scegliere i primi fix senza rilanciare analisi manuali.

### Task 5: Pay Down Core First-Party Errors In Batches

**Files:**
- Modify: prime aree candidate:
  - `lb_runner/engine/stop_token.py`
  - `lb_controller/engine/interrupts.py`
  - `lb_app/services/run_output.py`
  - `lb_ui/notifications/providers/desktop.py`

**Step 1: Pick one batch**

Scegliere un gruppo omogeneo di errori, per esempio:
- solo `no-untyped-def` nei moduli controller/runner
- solo `no-any-return` nei parser/output helpers

**Step 2: Add or tighten tests if behavior is risky**

Per moduli con logica runtime o signal handling, aggiungere test prima del refactor tipologico.

**Step 3: Implement minimal typing fixes**

- annotazioni mancanti
- cast mirati
- refactor piccoli per evitare `Any` o `Optional` ambigui
- rimozione `type: ignore` inutili

**Step 4: Re-run verification**

Run:
```bash
uv run pytest <subset-rilevante> -q
uv run mypy <comando-core>
```

Expected: il batch riduce errori senza regressioni funzionali.

### Task 6: Decide CI Policy

**Files:**
- Modify: CI workflow or contributing docs, depending on current practice

**Step 1: Decide target**

Scegliere quale comando deve essere blocking in CI:
- solo `mypy-core`
- oppure `mypy-core` blocking + `mypy-all` advisory

**Step 2: Implement/document**

Aggiornare workflow o documentazione per allineare il comportamento reale con quello atteso dal team.

**Step 3: Verify**

Expected: chi sviluppa sa quale comando deve essere verde prima di aprire una PR.
