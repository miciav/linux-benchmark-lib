"""Unit tests for provisioning lifecycle and preservation logic."""

from unittest.mock import MagicMock

import pytest

from lb_provisioner.types import ProvisionedNode, ProvisioningResult


@pytest.fixture
def nodes():
    mock_node1 = MagicMock(spec=ProvisionedNode)
    mock_node1.teardown = MagicMock()
    mock_node2 = MagicMock(spec=ProvisionedNode)
    mock_node2.teardown = MagicMock()
    return [mock_node1, mock_node2]


def test_destroy_all_teardowns_nodes_by_default(nodes):
    result = ProvisioningResult(nodes=nodes)
    result.destroy_all()
    
    for node in nodes:
        node.teardown.assert_called_once()


def test_destroy_all_skips_if_keep_nodes_is_true(nodes):
    result = ProvisioningResult(nodes=nodes, keep_nodes=True)
    result.destroy_all()
    
    for node in nodes:
        node.teardown.assert_not_called()


def test_destroy_all_skips_if_keep_nodes_set_dynamically(nodes):
    result = ProvisioningResult(nodes=nodes)
    result.keep_nodes = True
    result.destroy_all()
    
    for node in nodes:
        node.teardown.assert_not_called()
