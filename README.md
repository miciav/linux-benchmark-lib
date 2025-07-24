# Linux Benchmark Library

Una libreria Python robusta e configurabile per il benchmarking delle performance di nodi computazionali Linux.

## Descrizione

Questa libreria permette l'estrazione di array di valori dettagliati per diverse metriche di sistema, ottenuti in varie condizioni di traffico generate artificialmente. L'obiettivo è fornire una valutazione completa delle performance del sistema, evidenziando la variabilità tra le ripetizioni dei test.

## Caratteristiche Principali

- **Raccolta Metriche Multi-livello**: Supporta PSUtil, CLI tools Linux, perf events, e eBPF
- **Generatori di Carico Flessibili**: stress-ng, iperf3, dd, fio
- **Aggregazione Dati Intelligente**: DataFrame Pandas con metriche come indici e ripetizioni come colonne
- **Report Completi**: Report testuali e visualizzazioni grafiche
- **Altamente Configurabile**: Configurazione centralizzata tramite dataclasses

## Requisiti

- Python 3.13+
- Sistema operativo Linux (per funzionalità complete)
- Privilegi root per alcune funzionalità (perf, eBPF)

### Dipendenze Python

```bash
psutil>=5.9.0
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
seaborn>=0.12.0
iperf3>=0.1.11
performance>=0.3.0
jc>=1.23.0
influxdb-client>=1.36.0
```

### Software Esterni Richiesti

- **sysstat**: sar, vmstat, iostat, mpstat, pidstat
- **stress-ng**: Generatore di carico versatile
- **iperf3**: Test di rete
- **fio**: Test I/O avanzati
- **perf**: Profiling Linux
- **bcc/eBPF tools**: (Opzionale) Per metriche kernel avanzate

## Installazione

1. Clona il repository:
```bash
git clone <repository-url>
cd linux-benchmark-lib
```

2. Installa con uv:
```bash
uv venv
uv pip install -e .
```

3. Installa le dipendenze di sviluppo:
```bash
uv pip install -e ".[dev]"
```

## Utilizzo Rapido

```python
from benchmark_config import BenchmarkConfig
from orchestrator import Orchestrator

# Crea configurazione
config = BenchmarkConfig(
    repetitions=3,
    test_duration_seconds=60,
    metrics_interval_seconds=1.0
)

# Crea orchestrator
orchestrator = Orchestrator(config)

# Esegui benchmark CPU/Memory
orchestrator.run_benchmark("stress_ng")

# Esegui tutti i benchmark
orchestrator.run_all_benchmarks()
```

## Struttura del Progetto

```
linux-benchmark-lib/
├── benchmark_config.py      # Configurazione centralizzata
├── orchestrator.py          # Gestione del processo di benchmark
├── data_handler.py          # Elaborazione e aggregazione dati
├── reporter.py              # Generazione report e visualizzazioni
├── metric_collectors/       # Collezionisti di metriche
│   ├── __init__.py
│   ├── _base_collector.py   # Classe base astratta
│   ├── psutil_collector.py  # Metriche PSUtil
│   ├── cli_collector.py     # Metriche da CLI tools
│   ├── perf_collector.py    # Eventi perf
│   └── ebpf_collector.py    # Metriche eBPF
├── workload_generators/     # Generatori di carico
│   ├── __init__.py
│   ├── _base_generator.py   # Classe base astratta
│   ├── stress_ng_generator.py
│   ├── iperf3_generator.py
│   ├── dd_generator.py
│   └── fio_generator.py
├── tests/                   # Test unitari e di integrazione
├── docs/                    # Documentazione
└── pyproject.toml          # Configurazione progetto
```

## Configurazione

La configurazione è gestita tramite la classe `BenchmarkConfig`:

```python
from benchmark_config import BenchmarkConfig, StressNGConfig

config = BenchmarkConfig(
    # Parametri di esecuzione test
    repetitions=5,
    test_duration_seconds=120,
    metrics_interval_seconds=0.5,
    
    # Configurazione stress-ng
    stress_ng=StressNGConfig(
        cpu_workers=4,
        vm_workers=2,
        vm_bytes="2G"
    )
)

# Salva configurazione
config.save(Path("my_config.json"))

# Carica configurazione
config = BenchmarkConfig.load(Path("my_config.json"))
```

## Output

I risultati vengono salvati in tre directory:

- `benchmark_results/`: Dati raw delle metriche
- `reports/`: Report testuali e grafici
- `data_exports/`: Dati aggregati in formato CSV/JSON

Il DataFrame finale ha questa struttura:
- **Indice**: Nomi delle metriche (es. `cpu_usage_percent_avg`)
- **Colonne**: Ripetizioni del test (es. `Repetition_1`, `Repetition_2`)
- **Valori**: Valori aggregati per ogni metrica in ogni ripetizione

## Testing

Esegui i test con pytest:

```bash
pytest tests/
```

## Contribuire

1. Fork il progetto
2. Crea un branch per la tua feature (`git checkout -b feature/AmazingFeature`)
3. Commit le tue modifiche (`git commit -m 'Add some AmazingFeature'`)
4. Push al branch (`git push origin feature/AmazingFeature`)
5. Apri una Pull Request

## Licenza

Distribuito sotto licenza MIT. Vedi `LICENSE` per maggiori informazioni.
