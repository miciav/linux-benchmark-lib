Create a pytest end-to-end (e2e) test case that performs the following steps to verify the DFaaS benchmark workflow using Multipass VMs.

### 1. Infrastructure Setup & Architecture
- Use `multipass` to provision two virtual machines with **Ubuntu 24.04**:
  - **Target Node (`dfaas-target`):** This node will act as the **Runner/Controller** in the remote execution context. It will run the `lb` logic, host the OpenFaaS gateway/Prometheus (simulated or actual), and orchestrate the Generator node.
  - **Generator Node (`dfaas-generator`):** This node will host `k6` and generate load against the Target.
- **Network & SSH:**
  - Ensure the test runner (host machine) has SSH access to both VMs.
  - **Crucial:** Ensure `dfaas-target` has SSH access to `dfaas-generator` so it can execute Ansible playbooks and run k6 commands remotely.
- **Prerequisites on Target:**
  - The test must ensure (or verify) that `ansible-playbook` and `faas-cli` are installed on `dfaas-target`, as the DFaaS plugin requires them for orchestration.

### 2. Configuration Generation
- Dynamically generate a configuration file named `benchmark_config.dfaas_multipass.json`.
- Refer to `scripts/setup_dfaas_multipass.sh` for logic, but ensure the config includes:
  - **Remote Hosts:** Define `dfaas-target` as the remote host where the benchmark runs.
  - **Plugin Settings (`plugins.dfaas`):**
    - `k6_host`: IP of `dfaas-generator`.
    - `k6_ssh_key`: Path to the private key on `dfaas-target` (e.g., `/home/ubuntu/.ssh/dfaas_k6_key`).
    - `gateway_url` & `prometheus_url`: Points to `dfaas-target` IPs (or localhost if running on target).
    - **Minimal Test Config:**
      - `rates`: `min_rate: 10`, `max_rate: 10`, `step: 10` (single rate).
      - `combinations`: `min_functions: 1`, `max_functions: 2` (single combination).
      - `iterations`: 1 (single run).
      - `duration`: "10s" (short duration).
      - `functions`: A simple "env" or "echo" function.

### 3. Benchmark Execution
- Execute the benchmark using the library's CLI runner:
  ```bash
  uv run lb run --remote -c benchmark_config.dfaas_multipass.json
  ```
- This triggers the remote execution: Host -> connects to `dfaas-target` -> runs `lb` -> connects to `dfaas-generator` (for k6).

### 4. Verification Steps
After execution, verify the following artifacts on the **Target Node** (or locally if fetched):

- **Artifact Existence:** Check for the creation of the output directory (e.g., `benchmark_results/dfaas/`).
- **Specific Files:**
  - `results.csv`: Should contain rows with performance metrics (latency, success rate).
  - `summaries/summary-*.json`: detailed k6 execution stats.
  - `k6_scripts/*.js`: The generated k6 script.
- **Content Validation:**
  - `results.csv` should have `success_rate_function_...` > 0 (assuming success).
  - Log files on `dfaas-generator` (k6 logs) should indicate load generation.
- **Event Flow:** Verify `lb_event`s were generated and received by the controller.
