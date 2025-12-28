## Installation

1. Clone the repository:

```bash
git clone https://github.com/miciav/linux-benchmark-lib.git
cd linux-benchmark-lib
```

2. Create a virtual environment and install:

```bash
uv venv
uv pip install -e .  # runner only
```

### Extras

```bash
uv pip install -e ".[ui]"          # CLI/TUI
uv pip install -e ".[controller]"  # Ansible + analytics
uv pip install -e ".[ui,controller]"  # full CLI
uv pip install -e ".[dev]"         # test + lint tools
uv pip install -e ".[docs]"        # mkdocs
```

Switch between dependency sets with the helper script:

```bash
bash scripts/switch_mode.sh base
bash scripts/switch_mode.sh controller
bash scripts/switch_mode.sh headless
bash scripts/switch_mode.sh dev
```
