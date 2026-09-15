"""Unit tests for ensure_aap.py."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aap_configuration_e2e.cluster import DeployFailedError
from aap_configuration_e2e.errors import EnsureError
from aap_configuration_e2e.ensure_aap import (
    aap_demo_subprocess_env,
    effective_crc_version,
    ensure,
    find_aap_demo,
    get_crc_bundle_openshift_version,
    openshift_version_meets_minimum,
)


def test_find_aap_demo_uses_env(monkeypatch, tmp_path):
    script = tmp_path / "aap-demo.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setenv("AAP_DEMO_BIN", str(script))
    assert find_aap_demo() == script


def test_ensure_fast_path_writes_env(tmp_path):
    write_env = tmp_path / "aap-env.yml"
    fake_data = {
        "KUBECONFIG": "/tmp/kube",
        "aap_hostname": "aap.example.com",
        "aap_username": "admin",
        "aap_password": "secret",
        "aap_validate_certs": False,
        "aap_configuration_secure_logging": False,
    }

    with patch("aap_configuration_e2e.ensure_aap.platform_healthy", return_value=True):
        with patch("aap_configuration_e2e.ensure_aap.export_env", return_value=fake_data):
            result = ensure(write_env=write_env)

    assert result == fake_data
    assert write_env.is_file()
    assert "aap.example.com" in write_env.read_text()


def test_ensure_missing_pull_secret_exits(tmp_path, monkeypatch):
    write_env = tmp_path / "aap-env.yml"
    monkeypatch.delenv("AAP_DEMO_BIN", raising=False)

    with patch("aap_configuration_e2e.ensure_aap.platform_healthy", return_value=False):
        with patch("aap_configuration_e2e.ensure_aap.kubeconfig_ready", return_value=False):
            with patch(
                "aap_configuration_e2e.ensure_aap.PULL_SECRET",
                Path("/nonexistent/pull-secret.txt"),
            ):
                with pytest.raises(EnsureError) as exc:
                    ensure(write_env=write_env)
                assert "pull secret" in str(exc.value).lower()


def test_ensure_calls_deploy_non_interactive(tmp_path):
    write_env = tmp_path / "aap-env.yml"
    fake_data = {
        "KUBECONFIG": "/tmp/kube",
        "aap_hostname": "aap.example.com",
        "aap_username": "admin",
        "aap_password": "secret",
        "aap_validate_certs": False,
        "aap_configuration_secure_logging": False,
    }

    with patch("aap_configuration_e2e.ensure_aap.platform_healthy", return_value=False):
        with patch("aap_configuration_e2e.ensure_aap.kubeconfig_ready", return_value=True):
            with patch("aap_configuration_e2e.ensure_aap.PULL_SECRET", Path("/exists")):
                with patch("aap_configuration_e2e.ensure_aap.find_aap_demo") as mock_find:
                    mock_find.return_value = Path("/bin/aap-demo")
                    with patch(
                        "aap_configuration_e2e.ensure_aap.get_installed_crc_openshift_version",
                        return_value="4.21",
                    ):
                        with patch(
                            "aap_configuration_e2e.ensure_aap.ensure_nfs_storage_class"
                        ):
                            with patch(
                                "aap_configuration_e2e.ensure_aap.get_aap_conditions",
                                return_value=None,
                            ):
                                with patch(
                                    "aap_configuration_e2e.ensure_aap.run_aap_demo_deploy"
                                ) as mock_deploy:
                                    with patch(
                                        "aap_configuration_e2e.ensure_aap.export_env",
                                        return_value=fake_data,
                                    ):
                                        with patch(
                                            "aap_configuration_e2e.ensure_aap.wait_until_platform_healthy"
                                        ):
                                            with patch(
                                                "aap_configuration_e2e.ensure_aap.wait_ping"
                                            ):
                                                ensure(write_env=write_env)

    mock_deploy.assert_called_once()
    assert mock_deploy.call_args[1]["env"]["CRC_VERSION"] == "4.21"


def test_ensure_cleans_failed_aap_before_deploy(tmp_path):
    write_env = tmp_path / "aap-env.yml"
    fake_data = {
        "KUBECONFIG": "/tmp/kube",
        "aap_hostname": "aap.example.com",
        "aap_username": "admin",
        "aap_password": "secret",
        "aap_validate_certs": False,
        "aap_configuration_secure_logging": False,
    }
    from aap_configuration_e2e.cluster import AapConditions

    with patch("aap_configuration_e2e.ensure_aap.platform_healthy", return_value=False):
        with patch("aap_configuration_e2e.ensure_aap.kubeconfig_ready", return_value=True):
            with patch("aap_configuration_e2e.ensure_aap.PULL_SECRET", Path("/exists")):
                with patch("aap_configuration_e2e.ensure_aap.find_aap_demo") as mock_find:
                    mock_find.return_value = Path("/projects/aap-demo/aap-demo.sh")
                    with patch("aap_configuration_e2e.ensure_aap.ensure_nfs_storage_class"):
                        with patch(
                            "aap_configuration_e2e.ensure_aap.get_aap_conditions",
                            return_value=AapConditions(
                                successful=False,
                                failure=True,
                                failure_message="Failed",
                            ),
                        ):
                            with patch(
                                "aap_configuration_e2e.ensure_aap.run_aap_demo"
                            ) as mock_run:
                                with patch(
                                    "aap_configuration_e2e.ensure_aap.run_aap_demo_deploy"
                                ):
                                    with patch(
                                        "aap_configuration_e2e.ensure_aap.export_env",
                                        return_value=fake_data,
                                    ):
                                        with patch(
                                            "aap_configuration_e2e.ensure_aap.wait_until_platform_healthy"
                                        ):
                                            with patch(
                                                "aap_configuration_e2e.ensure_aap.wait_ping"
                                            ):
                                                ensure(write_env=write_env)

    mock_run.assert_called_once()
    assert mock_run.call_args[0][1] == "clean"


def test_ensure_retries_recoverable_gateway_failure(tmp_path, monkeypatch):
    write_env = tmp_path / "aap-env.yml"
    fake_data = {
        "KUBECONFIG": "/tmp/kube",
        "aap_hostname": "aap.example.com",
        "aap_username": "admin",
        "aap_password": "secret",
        "aap_validate_certs": False,
        "aap_configuration_secure_logging": False,
    }
    monkeypatch.setenv("AAP_E2E_DEPLOY_ATTEMPTS", "2")
    gateway_error = DeployFailedError(
        'AAP deployment failed: Failed to execute on pod aap-gateway-697d89854-wxnmv'
    )

    with patch("aap_configuration_e2e.ensure_aap.platform_healthy", return_value=False):
        with patch("aap_configuration_e2e.ensure_aap.kubeconfig_ready", return_value=True):
            with patch("aap_configuration_e2e.ensure_aap.PULL_SECRET", Path("/exists")):
                with patch("aap_configuration_e2e.ensure_aap.find_aap_demo") as mock_find:
                    mock_find.return_value = Path("/projects/aap-demo/aap-demo.sh")
                    with patch("aap_configuration_e2e.ensure_aap.ensure_nfs_storage_class"):
                        with patch(
                            "aap_configuration_e2e.ensure_aap.get_aap_conditions",
                            return_value=None,
                        ):
                            with patch(
                                "aap_configuration_e2e.ensure_aap.run_aap_demo"
                            ) as mock_run:
                                with patch(
                                    "aap_configuration_e2e.ensure_aap.run_aap_demo_deploy",
                                    side_effect=[gateway_error, None],
                                ):
                                    with patch(
                                        "aap_configuration_e2e.ensure_aap.export_env",
                                        return_value=fake_data,
                                    ):
                                        with patch(
                                            "aap_configuration_e2e.ensure_aap.wait_until_platform_healthy"
                                        ):
                                            with patch(
                                                "aap_configuration_e2e.ensure_aap.wait_ping"
                                            ):
                                                ensure(write_env=write_env)

    assert mock_run.call_count == 1
    assert mock_run.call_args[0][1] == "clean"


def test_aap_demo_subprocess_env_skips_ca_trust_by_default(monkeypatch):
    monkeypatch.delenv("AAP_E2E_TRUST_CA", raising=False)
    monkeypatch.delenv("AAP_E2E_CRC_VERSION", raising=False)
    monkeypatch.delenv("CRC_VERSION", raising=False)
    with patch(
        "aap_configuration_e2e.ensure_aap.get_installed_crc_openshift_version",
        return_value="4.21",
    ):
        env = aap_demo_subprocess_env()
    assert env["AAP_DEMO_TRUST_CA"] == "false"
    assert env["CRC_VERSION"] == "4.21"
    assert env["CRC_CPUS"] == "8"
    assert env["SKIP_TEMP_SWAP"] == "true"


def test_effective_crc_version_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("AAP_E2E_CRC_VERSION", "4.22")
    assert effective_crc_version() == "4.22"


def test_get_crc_bundle_openshift_version(tmp_path, monkeypatch):
    cache = tmp_path / ".crc" / "cache"
    cache.mkdir(parents=True)
    (cache / "crc_microshift_vfkit_4.21.0_arm64.crcbundle").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_crc_bundle_openshift_version() == "4.21"


def test_openshift_version_meets_minimum():
    assert openshift_version_meets_minimum("4.22", "4.22")
    assert openshift_version_meets_minimum("4.23", "4.22")
    assert not openshift_version_meets_minimum("4.21", "4.22")


def test_run_aap_demo_suppresses_subprocess_stdout():
    with patch("aap_configuration_e2e.ensure_aap.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from aap_configuration_e2e.ensure_aap import run_aap_demo

        run_aap_demo(Path("/bin/aap-demo"), "start", env={"PATH": "/"}, timeout=30)

    assert mock_run.call_args.kwargs["stdout"] == subprocess.DEVNULL


def test_run_aap_demo_deploy_suppresses_subprocess_stdout():
    with patch("aap_configuration_e2e.ensure_aap.subprocess.Popen") as mock_popen:
        proc = MagicMock()
        proc.poll.return_value = 0
        mock_popen.return_value = proc
        from aap_configuration_e2e.ensure_aap import run_aap_demo_deploy

        run_aap_demo_deploy(Path("/bin/aap-demo"), env={"PATH": "/"}, timeout=30)

    assert mock_popen.call_args.kwargs["stdout"] == subprocess.DEVNULL


def test_aap_demo_subprocess_env_allows_ca_trust_when_requested(monkeypatch):
    monkeypatch.setenv("AAP_E2E_TRUST_CA", "true")
    with patch(
        "aap_configuration_e2e.ensure_aap.get_installed_crc_openshift_version",
        return_value=None,
    ):
        with patch(
            "aap_configuration_e2e.ensure_aap.get_crc_bundle_openshift_version",
            return_value=None,
        ):
            env = aap_demo_subprocess_env()
    assert "AAP_DEMO_TRUST_CA" not in env or env.get("AAP_DEMO_TRUST_CA") != "false"
