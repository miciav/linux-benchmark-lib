# Geekbench Plugin

Questo plugin esegue Geekbench 6 (CPU o Compute) e salva i risultati raw in `geekbench_results.json`.

## Output CSV
Il plugin esporta nella cartella del workload:
- `geekbench_plugin.csv`: una riga per ripetizione con `single_core_score`, `multi_core_score`, metadati run/host e durata.
- `geekbench_subtests.csv` (se disponibile il JSON): elenco long‑form dei subtest con colonne `repetition`, `subtest`, `score`.

Se il JSON non è disponibile, `geekbench_plugin.csv` contiene solo metadati di base e i campi generator.
