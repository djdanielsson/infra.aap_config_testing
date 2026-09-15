"""AAP gateway URL, credentials, and health checks via kubectl."""

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from aap_configuration_e2e import (
    AAP_DEMO_NS_DEFAULT,
    KUBECONFIG_DEFAULT,
    PING_DELAY_SEC,
    PING_RETRIES,
)


def kubectl_json(args: list[str], kubeconfig: Path | None = None) -> dict:
    kc = kubeconfig or KUBECONFIG_DEFAULT
    env = {"KUBECONFIG": str(kc)}
    import os

    full_env = {**os.environ, **env}
    cmd = ["kubectl", *args, "-o", "json"]
    import subprocess

    result = subprocess.run(
        cmd,
        env=full_env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"kubectl {' '.join(args)} failed: {result.stderr.strip() or result.stdout}"
        )
    return json.loads(result.stdout)


def list_aap_crs(kubeconfig: Path | None = None) -> list[dict]:
    data = kubectl_json(["get", "aap", "-A"], kubeconfig)
    return data.get("items", [])


def aap_is_successful(cr: dict) -> bool:
    for cond in cr.get("status", {}).get("conditions", []):
        if cond.get("type") == "Successful" and cond.get("status") == "True":
            return True
    return False


def cr_status_summary(cr: dict | None) -> str:
    """Human-readable AAP CR status for errors and wait loops."""
    if cr is None:
        return "no AAP CR in cluster"
    ns = cr.get("metadata", {}).get("namespace", "?")
    name = cr.get("metadata", {}).get("name", "?")
    conditions = cr.get("status", {}).get("conditions", [])
    if not conditions:
        return f"{ns}/{name}: no status conditions yet"
    parts = [
        f"{c.get('type', '?')}={c.get('status', '?')}"
        for c in conditions
    ]
    return f"{ns}/{name}: " + ", ".join(parts)


def pick_aap_cr(items: list[dict]) -> dict:
    if not items:
        raise RuntimeError("No AnsibleAutomationPlatform CR found in cluster")
    for cr in items:
        if cr.get("metadata", {}).get("namespace") == AAP_DEMO_NS_DEFAULT:
            return cr
    return items[0]


def gateway_host(kubeconfig: Path | None, namespace: str) -> str:
    kc = kubeconfig or KUBECONFIG_DEFAULT
    try:
        route = kubectl_json(["get", "route", "aap", "-n", namespace], kc)
        host = route.get("spec", {}).get("host", "")
        if host:
            return host.removeprefix("https://").removeprefix("http://")
    except RuntimeError:
        pass

    routes = kubectl_json(["get", "route", "-n", namespace], kc)
    items = routes.get("items", [])
    for route in items:
        name = route.get("metadata", {}).get("name", "")
        host = route.get("spec", {}).get("host", "")
        if not host:
            continue
        host = host.removeprefix("https://").removeprefix("http://")
        if name == "aap" or host.startswith("aap"):
            return host
        if "controller" in name.lower() and host.startswith("controller-"):
            continue
        return host

    raise RuntimeError(f"No gateway route found in namespace {namespace}")


def admin_password(kubeconfig: Path | None, cr: dict) -> str:
    kc = kubeconfig or KUBECONFIG_DEFAULT
    ns = cr.get("metadata", {}).get("namespace", AAP_DEMO_NS_DEFAULT)
    secret_name = cr.get("status", {}).get("adminPasswordSecret")
    candidates = []
    if secret_name:
        candidates.append(secret_name)
    candidates.extend(["aap-admin-password", "myaap-admin-password"])

    for name in candidates:
        try:
            secret = kubectl_json(["get", "secret", name, "-n", ns], kc)
            raw = secret.get("data", {}).get("password", "")
            if raw:
                return base64.b64decode(raw).decode("utf-8")
        except RuntimeError:
            continue

    raise RuntimeError(f"Could not read admin password from namespace {ns}")


def gateway_ping_paths() -> list[str]:
    """Health-check paths for AAP 2.5+ gateway (preferred first)."""
    return [
        "/api/gateway/v1/ping/",
        "/api/controller/v2/ping/",
        "/api/v2/ping/",
    ]


def _ping_url(
    url: str,
    username: str | None,
    password: str | None,
    timeout: int,
) -> bool:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url)
    if username is not None and password is not None:
        cred = base64.b64encode(f"{username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ping(host: str, username: str, password: str, timeout: int = 10) -> bool:
    for path in gateway_ping_paths():
        url = f"https://{host}{path}"
        # Gateway ping is usually unauthenticated; try with credentials as fallback.
        if _ping_url(url, None, None, timeout):
            return True
        if _ping_url(url, username, password, timeout):
            return True
    return False


def wait_ping(
    host: str,
    username: str,
    password: str,
    retries: int = PING_RETRIES,
    delay: int = PING_DELAY_SEC,
) -> None:
    for attempt in range(retries):
        if ping(host, username, password):
            return
        if attempt < retries - 1:
            time.sleep(delay)
    primary = gateway_ping_paths()[0]
    raise RuntimeError(
        f"Gateway ping failed after {retries} attempts: https://{host}{primary}"
    )


def export_env(kubeconfig: Path | None = None) -> dict:
    kc = kubeconfig or KUBECONFIG_DEFAULT
    items = list_aap_crs(kc)
    cr = pick_aap_cr(items)
    if not aap_is_successful(cr):
        raise RuntimeError(
            f"AAP CR is not in Successful state yet ({cr_status_summary(cr)})"
        )
    ns = cr.get("metadata", {}).get("namespace", AAP_DEMO_NS_DEFAULT)
    host = gateway_host(kc, ns)
    password = admin_password(kc, cr)
    return {
        "KUBECONFIG": str(kc),
        "aap_hostname": host,
        "aap_username": "admin",
        "aap_password": password,
        "aap_validate_certs": False,
        "aap_configuration_secure_logging": False,
    }


def write_env_yaml(data: dict, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    path.chmod(0o600)


def platform_healthy(kubeconfig: Path | None = None) -> bool:
    kc = kubeconfig or KUBECONFIG_DEFAULT
    if not kc.is_file():
        return False
    try:
        import os
        import subprocess

        subprocess.run(
            ["kubectl", "get", "ns"],
            env={**os.environ, "KUBECONFIG": str(kc)},
            capture_output=True,
            check=True,
            timeout=30,
        )
        items = list_aap_crs(kc)
        if not items:
            return False
        cr = pick_aap_cr(items)
        if not aap_is_successful(cr):
            return False
        ns = cr.get("metadata", {}).get("namespace", AAP_DEMO_NS_DEFAULT)
        host = gateway_host(kc, ns)
        password = admin_password(kc, cr)
        return ping(host, "admin", password)
    except Exception:
        return False


def wait_until_platform_healthy(
    *,
    timeout: int = PING_RETRIES * PING_DELAY_SEC,
    poll_interval: int = PING_DELAY_SEC,
    kubeconfig: Path | None = None,
) -> None:
    """Poll until the AAP CR is Successful and the gateway responds."""
    deadline = time.monotonic() + timeout
    last_status = "unknown"
    while time.monotonic() < deadline:
        if platform_healthy(kubeconfig):
            return
        try:
            items = list_aap_crs(kubeconfig)
            if items:
                last_status = cr_status_summary(pick_aap_cr(items))
            else:
                last_status = cr_status_summary(None)
        except Exception as exc:  # noqa: BLE001 - best-effort status for wait loop
            last_status = str(exc)
        time.sleep(poll_interval)
    raise RuntimeError(
        f"AAP platform not ready after {timeout}s (last status: {last_status}). "
        "Check: kubectl get aap -A -o yaml && aap-demo deploy"
    )
