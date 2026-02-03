from __future__ import annotations

import pytest
from unittest.mock import patch
from lb_plugins.plugins.dfaas.generator import DfaasGenerator
from lb_plugins.plugins.dfaas.context import ExecutionContext
from lb_plugins.plugins.dfaas.config import DfaasConfig, DfaasFunctionConfig

@pytest.fixture
def generator():
    config = DfaasConfig(
        prometheus_url="http://{host.address}:30411",
        # Minimal required config
        functions=[DfaasFunctionConfig(name="dummy")], 
    )
    # Provide a dummy context, though _resolve_prometheus_url mostly uses arguments or internal methods
    exec_ctx = ExecutionContext(
        host="default-host",
        host_address="192.168.1.99",
        repetition=1,
        total_repetitions=1
    )
    return DfaasGenerator(config, execution_context=exec_ctx)

def test_resolve_prometheus_url_prioritizes_host_address(generator):
    """Test that host_address from context is used over target_name."""
    # Context has host_address="192.168.1.99"
    target = "ignored-hostname"
    resolved = generator._resolve_prometheus_url(target)
    assert resolved == "http://192.168.1.99:30411"

def test_resolve_prometheus_url_fallback_to_target_name():
    """Test fallback to target_name if host_address is missing."""
    config = DfaasConfig(
        prometheus_url="http://{host.address}:30411",
        functions=[DfaasFunctionConfig(name="dummy")]
    )
    exec_ctx = ExecutionContext(host="h1", repetition=1, total_repetitions=1) # No host_address
    gen = DfaasGenerator(config, execution_context=exec_ctx)
    
    resolved = gen._resolve_prometheus_url("fallback-host")
    assert resolved == "http://fallback-host:30411"

def test_resolve_prometheus_url_no_template():
    config = DfaasConfig(prometheus_url="http://static-host:9090", functions=[DfaasFunctionConfig(name="dummy")])
    gen = DfaasGenerator(config)
    assert gen._resolve_prometheus_url("target-host") == "http://static-host:9090"

def test_resolve_prometheus_url_with_template_and_target():
    """Test that {host.address} is replaced by target_name if host_address is missing."""
    config = DfaasConfig(
        prometheus_url="http://{host.address}:30411",
        functions=[DfaasFunctionConfig(name="dummy")]
    )
    exec_ctx = ExecutionContext(host="default", repetition=1, total_repetitions=1)
    generator = DfaasGenerator(config, execution_context=exec_ctx)
    
    target = "192.168.1.50"
    resolved = generator._resolve_prometheus_url(target)
    assert resolved == "http://192.168.1.50:30411"

def test_resolve_prometheus_url_with_template_no_target():
    """Test fallback to local IP if target_name is empty and host_address is missing."""
    config = DfaasConfig(
        prometheus_url="http://{host.address}:30411",
        functions=[DfaasFunctionConfig(name="dummy")]
    )
    exec_ctx = ExecutionContext(host="default", repetition=1, total_repetitions=1)
    generator = DfaasGenerator(config, execution_context=exec_ctx)
    
    with patch.object(DfaasGenerator, "_get_local_ip", return_value="10.0.0.99"):
        resolved = generator._resolve_prometheus_url("")
        assert resolved == "http://10.0.0.99:30411"

def test_resolve_gateway_url_with_template():
    """Test that gateway_url is also resolved using _resolve_url_template logic."""
    config = DfaasConfig(
        gateway_url="http://{host.address}:31112",
        functions=[DfaasFunctionConfig(name="dummy")]
    )
    # Using host_address explicitly to verify priority logic applies here too
    exec_ctx = ExecutionContext(
        host="host1",
        host_address="192.168.1.88", 
        repetition=1,
        total_repetitions=1
    )
    generator = DfaasGenerator(config, execution_context=exec_ctx)
    
    # Check the resolved URL inside the initialized K6Runner
    assert generator._k6_runner.gateway_url == "http://192.168.1.88:31112"

def test_resolve_prometheus_url_localhost_replacement():
    """Test existing logic: localhost/127.0.0.1 is replaced by host address when set."""
    config = DfaasConfig(prometheus_url="http://localhost:30411", functions=[DfaasFunctionConfig(name="dummy")])
    exec_ctx = ExecutionContext(
        host="remote-target",
        host_address="10.0.0.5",
        repetition=1,
        total_repetitions=1,
    )
    gen = DfaasGenerator(config, execution_context=exec_ctx)
    
    resolved = gen._resolve_prometheus_url("remote-target")
    assert resolved == "http://10.0.0.5:30411"

def test_resolve_prometheus_url_template_precedence():
    """
    Test that {host.address} replacement happens before localhost logic.
    If template is present, it should be used.
    """
    config = DfaasConfig(prometheus_url="http://{host.address}:30411", functions=[DfaasFunctionConfig(name="dummy")])
    gen = DfaasGenerator(config)
    target = "192.168.1.10"
    
    resolved = gen._resolve_prometheus_url(target)
    assert resolved == "http://192.168.1.10:30411"
