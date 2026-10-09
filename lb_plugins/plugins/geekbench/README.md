# Geekbench Plugin

Questo plugin esegue Geekbench 6 (CPU o Compute) e salva i risultati raw in `geekbench_results.json`.

## Output CSV
Il plugin esporta nella cartella del workload:
- `geekbench_plugin.csv`: una riga per ripetizione con `single_core_score`, `multi_core_score`, metadati run/host e durata.
- `geekbench_subtests.csv` (se disponibile il JSON): elenco long‑form dei subtest con colonne `repetition`, `subtest`, `score`.

Se il JSON non è disponibile, `geekbench_plugin.csv` contiene solo metadati di base e i campi generator.

## Requisito: licenza Geekbench Pro

Il JSON con i punteggi esiste solo con una licenza **Geekbench Pro**
(`license_key`): l'opzione `--export-json` è una funzione Pro su ogni
architettura (verificato su 6.3.0 x86_64 e sulle build ARM 6.3.0–6.7.0, che su
Linux sono tutte "Preview"). Senza licenza Geekbench carica i risultati solo sul
Geekbench Browser e non scrive nulla in locale: `geekbench_plugin.csv` avrà le
colonne dei punteggi vuote e `geekbench_subtests.csv` non verrà creato. Sulle
build ARM Preview, se l'upload fallisce, la ripetizione termina con errore.

Con la licenza, il JSON di ogni ripetizione viene copiato accanto ai CSV nella
directory del workload, così arriva sul controller insieme agli altri risultati.
