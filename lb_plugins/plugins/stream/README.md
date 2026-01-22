# STREAM Plugin Packaging & Build Notes

Questo plugin integra il benchmark STREAM (repo: `jeffhammond/STREAM`) e fornisce:

- Un plugin Python per eseguire STREAM e parsare le metriche principali.
- Un flusso di build per creare un pacchetto `.deb` **stream-benchmark** per `amd64` e `arm64` usando Docker Buildx.
- Un playbook Ansible per installare il `.deb` su host remoti.

## Upstream
- File vendorizzati:
  - `upstream/stream.c`
  - `upstream/LICENSE.txt`
- Commit upstream usato per il vendoring: `6703f7504a38a8da96b353cadafa64d3c2d7a2d3`
- Versione STREAM rilevata: `5.10` (stampata dallo stesso benchmark).

## Config (compile-time)
STREAM supporta parametri compile-time senza modificare il sorgente:
- `STREAM_ARRAY_SIZE` (default upstream: `10000000`)
- `NTIMES` (default upstream: `10`, default plugin: `100`)

Il plugin compila una variante in workspace quando configuri valori diversi dai default (o se forzi `recompile=True`).

## Compilers
- `compilers`: lista di compiler da usare (es. `["gcc", "icc"]`).
- `allow_missing_compilers`: se `true`, ignora compiler mancanti con warning.
- Il playbook di setup puo installare Intel oneAPI se imposti `stream_install_intel_compiler=true`.
- Il teardown puo rimuovere i pacchetti con `stream_cleanup_intel_compiler=true`.

## Build `.deb` multi-arch via Docker Buildx
File:
- `Dockerfile.cross`: compila `stream.c` e produce `stream-benchmark_<versione>-1_<arch>.deb` in `/out/`.
- `build_stream_docker_cross.sh`: wrapper buildx che scrive gli artifact in una dir locale.

Esempi:
```bash
TARGET_ARCH=linux/amd64 bash lb_plugins/plugins/stream/build_stream_docker_cross.sh
TARGET_ARCH=linux/arm64 bash lb_plugins/plugins/stream/build_stream_docker_cross.sh
```

Il playbook Ansible cerca di default i `.deb` qui:
- `lb_plugins/plugins/stream/stream-benchmark_5.10-1_amd64.deb`
- `lb_plugins/plugins/stream/stream-benchmark_5.10-1_arm64.deb`

Se li metti altrove, passa `-e stream_deb_src=/path/to/stream-benchmark_...deb` al provisioning workload.

## Note runtime
- STREAM usa OpenMP: se imposti `threads > 0`, il plugin setta `OMP_NUM_THREADS`.
- STREAM alloca 3 array statici: memoria ≈ `3 * STREAM_ARRAY_SIZE * sizeof(double)`.
