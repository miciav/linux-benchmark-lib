# Prompt (agentic): Pubblicare documentazione su GitHub Pages (MkDocs)

## Ruolo
Sei un agente di coding autonomo nel repo `linux-benchmark-lib`. Devi creare un sito di documentazione e pubblicarlo su GitHub Pages.

## Obiettivo
Impostare e rilasciare una GitHub Page di documentazione usando **MkDocs + Material**, con deploy automatico via GitHub Actions.

## Contesto noto
- `docs/` è vuota.
- Progetto Python con `pyproject.toml` e gestione dipendenze tramite `uv`.
- Contenuti base disponibili in `README.md` e `CLI.md`.

## Assunzioni
- Il branch principale è `main`.
- La Pages sarà servita su `https://<owner>.github.io/<repo>/` (path standard).
- Il repo è pubblico oppure la Pages è abilitata per repo privato.

Se una di queste assunzioni non è vera, fermati e chiedi conferma.

## Vincoli
- Non modificare API o comportamento runtime.
- Usa Markdown per i contenuti.
- Mantieni stile e naming coerenti col repo.
- Niente dipendenze di rete durante test locali se non richiesto.

## Input richiesti dall’utente (se mancanti, chiedi prima di procedere)
1. Nome repo GitHub esatto: `<owner>/<repo>`.
2. Eventuale dominio custom o root differente.
3. Vuoi API docs automatiche da docstring? (sì/no).

## Deliverable finali
1. Extra `docs` in `pyproject.toml` con MkDocs + Material (e opzionale mkdocstrings).
2. Directory `docs/` popolata con pagine iniziali.
3. `mkdocs.yml` configurato (tema, nav, estensioni).
4. Workflow `.github/workflows/pages.yml` per build+deploy.
5. `README.md` aggiornato con badge/link docs.
6. Istruzioni per build/preview locale.

## Strategia generale
Procedi per passi verificabili. Dopo ogni passo, fai una check rapida locale (quando possibile) e registra ciò che hai fatto.

## Piano operativo agentic

### Step 1 — Aggiungi dipendenze docs
**Azione**
- Modifica `pyproject.toml` aggiungendo:
  ```toml
  [project.optional-dependencies]
  docs = [
    "mkdocs>=1.6",
    "mkdocs-material>=9.5",
  ]
  ```
- Se l’utente vuole API docs, aggiungi anche:
  ```toml
  "mkdocstrings[python]>=0.26",
  ```

**Verifica**
- `python -c "import mkdocs"` dopo installazione locale.

**Stop condition**
- Se `pyproject.toml` ha già un extra `docs` o conflitti, proponi merge e chiedi conferma.

---

### Step 2 — Crea struttura contenuti in `docs/`
**Azione**
- Crea `docs/` con:
  - `index.md`
  - `installation.md`
  - `quickstart.md`
  - `configuration.md`
  - `plugins.md`
  - `remote_execution.md`
  - `cli.md`
  - `contributing.md`
- Riutilizza `README.md` e `CLI.md` spezzando in sezioni chiare.

**Verifica**
- Ogni pagina deve avere titolo H1 e link interni coerenti.

**Stop condition**
- Se mancano contenuti chiave o l’utente vuole altra struttura nav, chiedi indicazioni.

---

### Step 3 — Configura MkDocs
**Azione**
- Crea `mkdocs.yml` in root:
  ```yml
  site_name: Linux Benchmark Library
  repo_url: https://github.com/<owner>/<repo>
  repo_name: <owner>/<repo>
  theme:
    name: material
    features:
      - navigation.tabs
      - navigation.sections
      - content.code.copy
  nav:
    - Home: index.md
    - Installazione: installation.md
    - Quickstart: quickstart.md
    - Configurazione: configuration.md
    - Workloads & Plugin: plugins.md
    - Remote Execution: remote_execution.md
    - CLI: cli.md
    - Contributing: contributing.md
  markdown_extensions:
    - admonition
    - codehilite
    - toc:
        permalink: true
  ```

**Verifica**
- `mkdocs build --strict` non deve segnalare errori di nav o link.

**Stop condition**
- Se `mkdocs build` fallisce per link o file mancanti, correggi prima di proseguire.

---

### Step 4 — Aggiungi workflow Pages
**Azione**
- Crea `.github/workflows/pages.yml`:
  ```yml
  name: Deploy docs
  on:
    push:
      branches: [main]
    workflow_dispatch:

  permissions:
    contents: read
    pages: write
    id-token: write

  concurrency:
    group: "pages"
    cancel-in-progress: true

  jobs:
    build:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: "3.13"
        - name: Install deps
          run: pip install -e ".[docs]"
        - name: Build site
          run: mkdocs build --strict
        - uses: actions/upload-pages-artifact@v3
          with:
            path: site
    deploy:
      needs: build
      runs-on: ubuntu-latest
      environment:
        name: github-pages
        url: ${{ steps.deployment.outputs.page_url }}
      steps:
        - id: deployment
          uses: actions/deploy-pages@v4
  ```

**Verifica**
- Il workflow deve produrre artifact `site/`.

**Stop condition**
- Se il branch di default non è `main`, chiedi il nome corretto e aggiorna il workflow.

---

### Step 5 — Verifica locale
**Azione**
- Installazione:
  - `uv venv && uv pip install -e ".[docs]"`
- Preview:
  - `mkdocs serve`

**Verifica**
- Navigazione corretta e rendering code blocks ok.

---

### Step 6 — Aggiorna README
**Azione**
- Aggiungi sezione “Documentation” con link a Pages.
- Aggiungi badge docs (se desiderato).

**Verifica**
- Link corretto e coerente col nome repo.

---

### Step 7 (opzionale) — Versioning docs
**Azione**
- Se richiesto: aggiungi `mike` e configura versioni `latest` + tag.

**Stop condition**
- Chiedi conferma prima di introdurre versioning.

## Criteri di accettazione
- `mkdocs build --strict` passa localmente.
- Workflow Pages su `main` è verde.
- Sito raggiungibile su `https://<owner>.github.io/<repo>/`.
- README rimanda chiaramente alla doc.
