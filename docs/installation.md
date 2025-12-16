## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd linux-benchmark-lib
```

### Mode 1: Agent (Lightweight)
Installs only the core dependencies for running benchmarks on a target node.

```bash
uv sync
# Or install as a tool
uv tool install .
```

### Mode 2: Controller (Full)
Installs the core plus orchestration tools (Ansible) and reporting libraries (Matplotlib, Seaborn).

```bash
uv sync --extra controller
# Or install as a tool
uv tool install ".[controller]"
```

### Development
Installs all dependencies including test and linting tools.

```bash
uv sync --all-extras --dev
```

Switch between modes quickly with the helper script:

```bash
bash tools/switch_mode.sh base        # core only
bash tools/switch_mode.sh controller  # adds controller extra
bash tools/switch_mode.sh dev         # dev + all extras
