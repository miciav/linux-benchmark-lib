# Piano di Progettazione: Run Journaling e Resilienza

**Obiettivo:** Permettere la ripresa (`resume`) di benchmark interrotti o falliti parzialmente, garantendo che i test già completati con successo non vengano ripetuti.

## 1. Nuova Entità: `BenchmarkState` (Il Journal)

Introdurre una nuova classe (`linux_benchmark_lib/journal.py`) per gestire lo stato.

**Struttura Dati:**
Deve mappare univocamente ogni singola "unità di lavoro" atomica: `(Host, Workload, Repetition)`.

```python
@dataclass
class TaskState:
    status: str  # PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    host: str
    workload: str
    repetition: int
    timestamp: float
    error: Optional[str] = None

@dataclass
class RunJournal:
    run_id: str
    config_snapshot: dict  # Per validare che stiamo riprendendo lo stesso lavoro
    tasks: Dict[str, TaskState]  # Chiave es: "host1::fio::1"
    
    def get_task_key(self, host, workload, rep): ...
    def update_task(self, host, workload, rep, status, error=None): ...
    def save(self, path): ...
    @classmethod
    def load(cls, path): ...
```

## 2. Modifiche all'API della CLI

*   **Nuovo flag `--resume <run_id>` (o solo `--resume`):**
    *   Cerca l'ultimo run (o quello specificato) nella directory di output.
    *   Carica `run_state.json`.
    *   Verifica la coerenza con la configurazione corrente.

## 3. Integrazione nel `BenchmarkController`

**Refactoring Necessario:**
Spostare il controllo del loop delle ripetizioni **dal LocalRunner (remoto) al Controller (locale)**.

*   **Attuale:** Il controller lancia un playbook che esegue uno script remoto che fa un loop 1..N.
*   **Nuovo:** Il controller itera 1..N e per ogni iterazione:
    1.  Verifica nel Journal se la ripetizione è fatta.
    2.  Se no, lancia il playbook per eseguire *una singola ripetizione*.
    3.  Aggiorna il Journal.

## 4. Flusso Operativo Aggiornato

1.  **Inizializzazione:**
    *   `lb run`: Se `--resume`, carica stato. Se nuovo, inizializza stato `PENDING`.
2.  **Esecuzione (Controller):**
    *   Itera sui task.
    *   Salta `COMPLETED`.
    *   Esegue `PENDING` -> Imposta `RUNNING` -> Lancia Ansible -> Imposta `COMPLETED`/`FAILED`.
3.  **Raccolta:**
    *   Mantenere la raccolta intermedia dopo ogni step o gruppo di step.

## 5. Dettaglio Tecnico: Adattare `LocalRunner` e Playbook

Modificare `linux_benchmark_lib/local_runner.py` per accettare argomenti per eseguire una specifica ripetizione (es. `--repetition-index 2 --single-run`).
Modificare il playbook `run_benchmark.yml` per passare questi parametri.
