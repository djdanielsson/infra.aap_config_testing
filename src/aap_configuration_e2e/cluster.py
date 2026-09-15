"""Cluster prerequisite checks for aap-demo / MicroShift."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aap_configuration_e2e import AAP_DEMO_NS_DEFAULT, KUBECONFIG_DEFAULT
from aap_configuration_e2e.errors import EnsureError

_RECOVERABLE_FAILURE_PATTERNS = (
    re.compile(r"failed to execute on pod aap-gateway", re.IGNORECASE),
    re.compile(r'pods?\s+"aap-gateway-[^"]+"\s+not found', re.IGNORECASE),
    re.compile(r"handshake status 404 not found", re.IGNORECASE),
)


@dataclass
class AapConditions:
    successful: bool
    failure: bool
    failure_message: str


class DeployFailedError(RuntimeError):
    """AAP deploy failed; message may be recoverable via clean + redeploy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def is_recoverable_deploy_failure(message: str) -> bool:
    """True when failure looks like a gateway pod rollout race, not a hard error."""
    if not message:
        return False
    return any(pattern.search(message) for pattern in _RECOVERABLE_FAILURE_PATTERNS)


def _kube_env() -> dict[str, str]:
    return {**os.environ, "KUBECONFIG": str(KUBECONFIG_DEFAULT)}


def kubectl_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        env=_kube_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout)
    return json.loads(result.stdout)


def storage_class_exists(name: str) -> bool:
    try:
        kubectl_json(["get", "sc", name])
        return True
    except RuntimeError:
        return False


def get_aap_conditions(namespace: str = AAP_DEMO_NS_DEFAULT) -> AapConditions | None:
    try:
        data = kubectl_json(["get", "aap", "-n", namespace])
    except RuntimeError:
        return None
    items = data.get("items", [])
    if not items:
        return None
    successful = False
    failure = False
    failure_message = ""
    for cond in items[0].get("status", {}).get("conditions", []):
        if cond.get("type") == "Successful" and cond.get("status") == "True":
            successful = True
        if cond.get("type") == "Failure" and cond.get("status") == "True":
            failure = True
            failure_message = cond.get("message") or cond.get("reason") or "Failed"
    return AapConditions(
        successful=successful,
        failure=failure,
        failure_message=failure_message,
    )


def pending_pod_events(namespace: str = AAP_DEMO_NS_DEFAULT, limit: int = 8) -> str:
    try:
        pods = kubectl_json(["get", "pods", "-n", namespace])
    except RuntimeError as exc:
        return str(exc)
    lines: list[str] = []
    for pod in pods.get("items", []):
        phase = pod.get("status", {}).get("phase", "")
        if phase not in ("Pending", "Failed"):
            continue
        name = pod["metadata"]["name"]
        reason = ""
        for cond in pod.get("status", {}).get("conditions", []):
            if cond.get("type") == "PodScheduled" and cond.get("status") != "True":
                reason = cond.get("message", "")
        lines.append(f"  {name}: {phase} {reason}".strip())
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def find_aap_demo_root(bin_path: Path) -> Path:
    return bin_path.resolve().parent


def ensure_nfs_storage_class(aap_demo_root: Path, timeout: int = 300) -> None:
    """Install nfs-local-rwx if missing (hub RWX volumes need it)."""
    if storage_class_exists("nfs-local-rwx"):
        return

    manifests = aap_demo_root / "config" / "manifests"
    nfs_server = manifests / "nfs-server.yaml"
    nfs_provisioner = manifests / "nfs-provisioner.yaml"
    if not nfs_server.is_file() or not nfs_provisioner.is_file():
        raise EnsureError(
            f"nfs-local-rwx StorageClass missing and cannot find NFS manifests under {manifests}"
        )

    print(
        "nfs-local-rwx StorageClass missing (hub pods will stay Pending). "
        "Installing NFS provisioner from aap-demo...",
        file=sys.stderr,
    )

    env = _kube_env()
    if shutil.which("oc"):
        subprocess.run(
            [
                "oc",
                "adm",
                "policy",
                "add-scc-to-group",
                "privileged",
                "system:serviceaccounts:nfs-storage",
            ],
            env=env,
            capture_output=True,
        )

    default_sc = "topolvm-provisioner"
    try:
        scs = kubectl_json(["get", "sc"])
        for item in scs.get("items", []):
            ann = item.get("metadata", {}).get("annotations", {})
            if ann.get("storageclass.kubernetes.io/is-default-class") == "true":
                default_sc = item["metadata"]["name"]
                break
    except RuntimeError:
        pass

    server_yaml = nfs_server.read_text(encoding="utf-8").replace("__DEFAULT_SC__", default_sc)
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=server_yaml,
        env=env,
        text=True,
        check=True,
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            subprocess.run(
                [
                    "kubectl",
                    "wait",
                    "--for=condition=Available",
                    "deployment/nfs-server",
                    "-n",
                    "nfs-storage",
                    "--timeout=30s",
                ],
                env=env,
                check=True,
                capture_output=True,
            )
            break
        except subprocess.CalledProcessError:
            time.sleep(5)
    else:
        raise EnsureError("Timed out waiting for nfs-server deployment")

    svc = subprocess.run(
        ["kubectl", "get", "svc", "nfs-server", "-n", "nfs-storage", "-o", "jsonpath={.spec.clusterIP}"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    nfs_ip = svc.stdout.strip()
    if not nfs_ip:
        raise EnsureError("Could not resolve nfs-server cluster IP")

    prov_yaml = nfs_provisioner.read_text(encoding="utf-8").replace("__NFS_SERVER_IP__", nfs_ip)
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=prov_yaml,
        env=env,
        text=True,
        check=True,
    )
    subprocess.run(
        [
            "kubectl",
            "wait",
            "--for=condition=Available",
            "deployment/nfs-provisioner",
            "-n",
            "nfs-storage",
            f"--timeout={timeout}s",
        ],
        env=env,
        check=True,
    )
    print("nfs-local-rwx StorageClass is ready.", file=sys.stderr)


def deployment_failure_hint(namespace: str = AAP_DEMO_NS_DEFAULT) -> str:
    hints: list[str] = []
    if not storage_class_exists("nfs-local-rwx"):
        hints.append(
            "- nfs-local-rwx StorageClass is missing (hub PVCs need RWX). "
            "Re-run the test or: aap-demo create"
        )
    pending = pending_pod_events(namespace)
    if pending:
        hints.append("- Pending/failed pods:\n" + pending)
    return "\n".join(hints)
