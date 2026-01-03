# DFAAS-QUALITY-3: Configurable Prometheus and OpenFaaS ports

## Context
The DFaaS plugin uses hardcoded NodePort values for Prometheus (30411) and OpenFaaS gateway (31112), which may conflict with existing services or violate cluster policies.

## Goal
Make port configuration explicit and add validation for conflicts.

## Scope
- Add port fields to DfaasConfig
- Pass ports to Ansible playbooks
- Add port conflict validation
- Maintain backward compatibility with defaults

## Non-scope
- ClusterIP/LoadBalancer service types
- Ingress configuration
- TLS setup

## Current State

### setup_target.yml (hardcoded defaults)
```yaml
vars:
  openfaas_gateway_node_port: 31112
  prometheus_node_port: 30411
```

### plugin.py (implicit in URLs)
```python
gateway_url: str = ""  # e.g., "http://10.0.0.1:31112"
prometheus_url: str = ""  # e.g., "http://10.0.0.1:30411"
```

Problems:
1. Port 30411/31112 may be in use
2. No validation that ports are in NodePort range (30000-32767)
3. Cannot easily change ports after setup

## Proposed Design

### Config Extension
```python
class DfaasConfig(BasePluginConfig):
    # Existing
    gateway_url: str = ""
    prometheus_url: str = ""

    # New - explicit port configuration for setup
    openfaas_node_port: int = Field(
        default=31112,
        ge=30000,
        le=32767,
        description="NodePort for OpenFaaS gateway service"
    )
    prometheus_node_port: int = Field(
        default=30411,
        ge=30000,
        le=32767,
        description="NodePort for Prometheus service"
    )

    @model_validator(mode='after')
    def validate_ports(self) -> 'DfaasConfig':
        if self.openfaas_node_port == self.prometheus_node_port:
            raise ValueError("openfaas_node_port and prometheus_node_port must be different")
        return self
```

### Ansible Variable Passing
```yaml
# setup_target.yml
vars:
  openfaas_gateway_node_port: "{{ dfaas_openfaas_node_port | default(31112) }}"
  prometheus_node_port: "{{ dfaas_prometheus_node_port | default(30411) }}"
```

### URL Auto-Discovery
```python
class DfaasConfig(BasePluginConfig):
    def get_gateway_url(self, target_ip: str) -> str:
        if self.gateway_url:
            return self.gateway_url
        return f"http://{target_ip}:{self.openfaas_node_port}"

    def get_prometheus_url(self, target_ip: str) -> str:
        if self.prometheus_url:
            return self.prometheus_url
        return f"http://{target_ip}:{self.prometheus_node_port}"
```

## Partial Objectives + Tests

### Objective 1: Add port fields to config
Define fields with validation.
**Tests**:
- Unit test: default values work
- Unit test: custom ports accepted
- Unit test: invalid port range rejected
- Unit test: duplicate ports rejected

### Objective 2: Update Ansible playbooks
Pass ports as variables.
**Tests**:
- Manual test: setup with custom ports
- Verify services accessible on configured ports

### Objective 3: Add URL helpers
Implement auto-discovery methods.
**Tests**:
- Unit test: URL generation with custom ports
- Unit test: explicit URL overrides auto-discovery

### Objective 4: Update documentation
Document port configuration in README.
**Tests**:
- Manual review

## Acceptance Criteria
- [ ] Ports configurable via DfaasConfig
- [ ] Validation rejects invalid/duplicate ports
- [ ] Ansible respects configured ports
- [ ] Backward compatible defaults
- [ ] Documentation updated

## Files to Modify
- `lb_plugins/plugins/dfaas/plugin.py`
- `lb_plugins/plugins/dfaas/ansible/setup_target.yml`
- `lb_plugins/plugins/dfaas/README.md`

## Files to Create
- Test cases in `tests/unit/lb_plugins/test_dfaas_config.py`

## Dependencies
- None (independent)

## Effort
~2 hours

