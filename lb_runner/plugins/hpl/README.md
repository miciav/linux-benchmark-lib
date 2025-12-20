# HPL Plugin Packaging & Build Notes

Questo plugin include alcuni strumenti per compilare HPL 2.3, impacchettarlo in un `.deb` e testarlo in ambienti isolati. Sono disponibili due flussi principali:

- **VM (Multipass)**: build e test su una VM dedicata.
- **Docker Buildx**: cross‑build multi‑arch tramite Docker.

Per l’esecuzione remota/multipass: il playbook `ansible/setup.yml` installa le dipendenze, copia il `.deb` precompilato per l’architettura corretta, esegue `dpkg -i` e replica `xhpl` nel workspace.

## File di packaging
- `Make.Linux`: configurazione HPL per OpenMPI/OpenBLAS (usata in make e packaging).
- `control`: metadati Debian per il pacchetto `hpl`.
- `rules`: `debian/rules` per compilare `xhpl` e assemblare il `.deb`.

## Script

### build_hpl_vm.sh
Crea una VM Multipass, installa dipendenze, copia i file di packaging e genera il `.deb` (solo binario).

- Variabili:
  - `VM_NAME` (default `hpl-build`)
  - `VM_ARCH` (se supportato da Multipass, es. `x86_64` o `aarch64`)
- Risorse VM: 10G RAM, 40G disco, 4 vCPU.
- Output: `hpl_2.3-1_*.deb` in `/home/ubuntu/hpl-deb/` dentro la VM.

Esempio:
```bash
VM_NAME=hpl-build-amd64 VM_ARCH=x86_64 bash lb_runner/plugins/hpl/build_hpl_vm.sh
```
Se Multipass non supporta `--arch`, usare un host/VM dell’architettura desiderata.

### test_hpl_vm.sh
Crea una VM Multipass, installa il `.deb` fornito, scrive un `HPL.dat` minimale e lancia `mpirun -np 1 ./xhpl` come smoke test.

- Variabili:
  - `VM_NAME` (default `hpl-test`)
  - `VM_ARCH` (opzionale, se supportato)
- Uso:
```bash
bash lb_runner/plugins/hpl/test_hpl_vm.sh /path/to/hpl_2.3-1_*.deb
```
Lo script installa runtime deps (`openmpi`, `openblas`), carica il deb, genera `HPL.dat` in `/opt/hpl-2.3/bin/Linux/` e avvia `xhpl`.

### Dockerfile.cross
Dockerfile multi‑stage che compila HPL 2.3 su Debian bookworm usando i file di packaging del plugin e produce il `.deb` in `/out/`.

### build_hpl_docker_cross.sh
Wrapper per Docker Buildx: costruisce il `.deb` per una piattaforma target e scrive gli artifact in una directory locale.

- Variabili:
  - `TARGET_ARCH` (default `linux/amd64`, es. `linux/arm64`)
  - `OUT_DIR` (default `out-${TARGET_ARCH//\//-}` nel repo)
  - `BUILDER` (default `hpl-cross-builder`)
- Uso:
```bash
TARGET_ARCH=linux/amd64 bash lb_runner/plugins/hpl/build_hpl_docker_cross.sh
```
Richiede Docker Buildx con binfmt/qemu abilitati per le architetture desiderate.

### Dockerfile.arm / Dockerfile.amd64
Dockerfile per costruire un’immagine docker che installa rispettivamente il `.deb` ARM64 o AMD64.

- Passa il percorso del `.deb` nel contesto con `--build-arg HPL_DEB=...` (default: `hpl_2.3-1_arm64.deb` o `hpl_2.3-1_amd64.deb`); usa percorsi relativi al contesto (es. `lb_runner/plugins/hpl/hpl_2.3-1_arm64.deb`).
- Se vuoi forzare l’architettura, usa `docker build --platform linux/arm64` o `--platform linux/amd64`.
- Esempi:
  ```bash
  docker build --platform linux/arm64  -f lb_runner/plugins/hpl/Dockerfile.arm   --build-arg HPL_DEB=lb_runner/plugins/hpl/hpl_2.3-1_arm64.deb .
  docker build --platform linux/amd64  -f lb_runner/plugins/hpl/Dockerfile.amd64 --build-arg HPL_DEB=lb_runner/plugins/hpl/hpl_2.3-1_amd64.deb .
  ```

### push_hpl_images.sh
Script helper per buildare e pushare su Docker Hub le immagini ARM64/AMD64 e creare un manifest multi-arch.

- Variabili:
  - `DOCKER_USER` (obbligatorio, username Docker Hub)
  - `BUILDER` (facoltativo, nome builder buildx, default `hpl-pusher`)
- Requisiti: buildx abilitato, login già effettuato (`docker login`).
- Esempio:
  ```bash
  DOCKER_USER=youruser bash lb_runner/plugins/hpl/push_hpl_images.sh
  ```

## Note operative
- Se la build HPL consuma troppa RAM, usa `HPL_MAKEFLAGS=-j1` (già impostato nei playbook e Dockerfile di build) o esegui la compilazione in una VM/Docker con più memoria.
- I pacchetti generati installano `xhpl` in `/opt/hpl-2.3/bin/Linux/`; `HPL.dat` va posizionato nella stessa directory prima di lanciare `mpirun ./xhpl`.

## Output CSV
Dopo ogni run, il plugin esporta un file `hpl_plugin.csv` nella cartella del workload.
Contiene una riga per ripetizione con le metriche principali:
- `repetition`, `duration_seconds`, `success`, `returncode`
- `n`, `nb`, `p`, `q`, `time_seconds`, `gflops`
- `residual` e `residual_passed`
- `result_line` (tag raw riga WR HPL)
