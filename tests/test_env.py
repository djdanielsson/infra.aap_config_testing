"""Unit tests for env.py."""

import base64
import json
from unittest.mock import patch

import pytest

from aap_configuration_e2e.env import (
    admin_password,
    aap_is_successful,
    cr_status_summary,
    gateway_host,
    gateway_ping_paths,
    ping,
    wait_until_platform_healthy,
)


def test_aap_is_successful_true():
    cr = {
        "status": {
            "conditions": [{"type": "Successful", "status": "True"}],
        }
    }
    assert aap_is_successful(cr) is True


def test_aap_is_successful_false():
    assert aap_is_successful({"status": {"conditions": []}}) is False


def test_cr_status_summary_includes_conditions():
    cr = {
        "metadata": {"namespace": "aap-operator", "name": "aap"},
        "status": {
            "conditions": [
                {"type": "Successful", "status": "False"},
                {"type": "Failure", "status": "False"},
            ],
        },
    }
    summary = cr_status_summary(cr)
    assert "aap-operator/aap" in summary
    assert "Successful=False" in summary


def test_write_env_yaml_accepts_string_path(tmp_path):
    from aap_configuration_e2e.env import write_env_yaml

    target = tmp_path / "nested" / "aap-env.yml"
    write_env_yaml({"aap_hostname": "example.com"}, str(target))
    assert target.is_file()


def test_wait_until_platform_healthy_returns_when_ready():
    with patch(
        "aap_configuration_e2e.env.platform_healthy",
        side_effect=[False, True],
    ):
        wait_until_platform_healthy(timeout=30, poll_interval=1)


def test_admin_password_decodes_secret():
    secret = {
        "data": {"password": base64.b64encode(b"secret").decode()},
    }
    cr = {
        "metadata": {"namespace": "aap-operator"},
        "status": {"adminPasswordSecret": "aap-admin-password"},
    }

    with patch("aap_configuration_e2e.env.kubectl_json", return_value=secret):
        assert admin_password(None, cr) == "secret"


def test_gateway_host_prefers_aap_route():
    route_aap = {"spec": {"host": "aap-aap-operator.apps.example.com"}}
    with patch("aap_configuration_e2e.env.kubectl_json", return_value=route_aap):
        assert gateway_host(None, "aap-operator") == "aap-aap-operator.apps.example.com"


def test_gateway_host_lists_routes_when_aap_missing():
    routes = {
        "items": [
            {
                "metadata": {"name": "controller"},
                "spec": {"host": "controller-aap-operator.apps.example.com"},
            },
            {
                "metadata": {"name": "aap"},
                "spec": {"host": "aap-aap-operator.apps.example.com"},
            },
        ]
    }

    def fake_kubectl(args, kubeconfig=None):
        if "route" in args and "aap" in args:
            raise RuntimeError("not found")
        return routes

    with patch("aap_configuration_e2e.env.kubectl_json", side_effect=fake_kubectl):
        assert gateway_host(None, "aap-operator") == "aap-aap-operator.apps.example.com"


def test_gateway_ping_paths_prefers_gateway_api():
    assert gateway_ping_paths()[0] == "/api/gateway/v1/ping/"


def test_ping_returns_false_on_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert ping("example.com", "admin", "pass") is False


def test_ping_uses_gateway_endpoint():
    seen_urls: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=10, context=None):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/api/gateway/v1/ping/"):
            return FakeResponse()
        raise OSError("not found")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert ping("aap.example.com", "admin", "pass") is True
    assert seen_urls[0] == "https://aap.example.com/api/gateway/v1/ping/"
