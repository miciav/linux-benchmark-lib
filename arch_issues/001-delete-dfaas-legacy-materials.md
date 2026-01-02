# Delete legacy_materials folder in dfaas plugin

## Problem

The folder `lb_plugins/plugins/dfaas/legacy_materials/` contains legacy Python code that:

1. **Has extreme complexity** - `samples-generator.py:main` has rank **E** (highest complexity)
2. **Has dependency issues** - imports `utils` module that isn't declared, uses `requests` as transitive dependency
3. **Is not used** - no imports from this folder found anywhere in the codebase
4. **Pollutes analysis** - triggers deptry, xenon, and bandit warnings

## Evidence

**Xenon complexity report** (`arch_report/xenon.txt`):
```
ERROR:xenon:block "lb_plugins/plugins/dfaas/legacy_materials/samples_generator/samples-generator.py:46 main" has a rank of E
ERROR:xenon:module 'lb_plugins/plugins/dfaas/legacy_materials/samples_generator/samples-generator.py' has a rank of E
```

**Deptry dependency issues** (`arch_report/deptry.txt`):
```
lb_plugins/plugins/dfaas/legacy_materials/samples_generator/samples-generator-profiler.py:13:1: DEP001 'utils' imported but missing
lb_plugins/plugins/dfaas/legacy_materials/samples_generator/samples-generator.py:16:8: DEP001 'utils' imported but missing
lb_plugins/plugins/dfaas/legacy_materials/samples_generator/utils.py:20:8: DEP003 'requests' imported but transitive
```

**Files to delete**:
```
lb_plugins/plugins/dfaas/legacy_materials/
├── README.md
├── data_collection_doc.md
├── infrastructure/
├── minikube_builder.sh
├── requirements.txt
└── samples_generator/
    ├── samples-generator.py (rank E)
    ├── samples-generator-profiler.py (rank C)
    └── utils.py (rank C)
```

## Solution

### Step 1: Verify no imports exist
```bash
grep -r "legacy_materials" --include="*.py" .
grep -r "samples_generator" --include="*.py" . | grep -v legacy_materials
```

### Step 2: Delete the folder
```bash
rm -rf lb_plugins/plugins/dfaas/legacy_materials/
```

### Step 3: Run tests
```bash
uv run pytest tests/unit/lb_plugins/test_dfaas*.py -v
```

### Step 4: Verify clean analysis
```bash
uv run deptry lb_plugins
```

## Risk Assessment

| Aspect | Level | Notes |
|--------|-------|-------|
| Risk | **Low** | No imports found, code is orphaned |
| Effort | **Trivial** | Single `rm -rf` command |
| Validation | Run unit tests for dfaas plugin |

## Acceptance Criteria

- [ ] `legacy_materials/` folder deleted
- [ ] No grep matches for `legacy_materials` in codebase
- [ ] `deptry` reports 0 issues for lb_plugins
- [ ] All dfaas tests pass
