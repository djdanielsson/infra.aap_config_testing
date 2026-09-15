"""Unit tests for cluster.py."""

from unittest.mock import MagicMock, patch

import pytest

from aap_configuration_e2e.cluster import (
    AapConditions,
    deployment_failure_hint,
    ensure_nfs_storage_class,
    get_aap_conditions,
    is_recoverable_deploy_failure,
    storage_class_exists,
)


def test_storage_class_exists_true():
    with patch("aap_configuration_e2e.cluster.kubectl_json", return_value={}):
        assert storage_class_exists("nfs-local-rwx") is True


def test_storage_class_exists_false():
    with patch(
        "aap_configuration_e2e.cluster.kubectl_json",
        side_effect=RuntimeError("not found"),
    ):
        assert storage_class_exists("nfs-local-rwx") is False


def test_get_aap_conditions_parses_failure():
    payload = {
        "items": [
            {
                "status": {
                    "conditions": [
                        {"type": "Successful", "status": "False"},
                        {"type": "Failure", "status": "True", "message": "hub failed"},
                    ]
                }
            }
        ]
    }
    with patch("aap_configuration_e2e.cluster.kubectl_json", return_value=payload):
        cond = get_aap_conditions()
    assert cond == AapConditions(
        successful=False,
        failure=True,
        failure_message="hub failed",
    )


def test_ensure_nfs_storage_class_skips_when_present(tmp_path):
    with patch("aap_configuration_e2e.cluster.storage_class_exists", return_value=True):
        ensure_nfs_storage_class(tmp_path)


def test_ensure_nfs_storage_class_missing_manifests(tmp_path):
    with patch("aap_configuration_e2e.cluster.storage_class_exists", return_value=False):
        from aap_configuration_e2e.errors import EnsureError

        with pytest.raises(EnsureError) as exc:
            ensure_nfs_storage_class(tmp_path)
        assert "manifests" in str(exc.value).lower()


def test_deployment_failure_hint_includes_nfs():
    with patch("aap_configuration_e2e.cluster.storage_class_exists", return_value=False):
        hint = deployment_failure_hint()
    assert "nfs-local-rwx" in hint


def test_is_recoverable_deploy_failure_gateway_pod_race():
    message = (
        'Failed to execute on pod aap-gateway-697d89854-wxnmv due to : (0)\n'
        'Reason: Handshake status 404 Not Found ... pods "aap-gateway-697d89854-wxnmv" not found'
    )
    assert is_recoverable_deploy_failure(message)


def test_is_recoverable_deploy_failure_rejects_hub_errors():
    assert not is_recoverable_deploy_failure("hub content pod failed to start")
