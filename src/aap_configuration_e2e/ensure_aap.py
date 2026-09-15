"""Ensure CRC and AAP are running via aap-demo."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aap_configuration_e2e import DEPLOY_TIMEOUT_SEC, KUBECONFIG_DEFAULT, PULL_SECRET
from aap_configuration_e2e.errors import EnsureError
from aap_configuration_e2e.cluster import (
    DeployFailedError,
    deployment_failure_hint,
    ensure_nfs_storage_class,
    find_aap_demo_root,
    get_aap_conditions,
    is_recoverable_deploy_failure,
)
from aap_configuration_e2e.env import (
    cr_status_summary,
    export_env,
    list_aap_crs,
    pick_aap_cr,
    platform_healthy as env_platform_healthy,
    wait_ping,
    wait_until_platform_healthy,
    write_env_yaml,
)


def find_aap_demo() -> Path:
    candidates: list[Path | str] = []
    if os.environ.get("AAP_DEMO_BIN"):
        candidates.append(Path(os.environ["AAP_DEMO_BIN"]))
    which = shutil.which("aap-demo")
    if which:
        candidates.append(Path(which))
    candidates.append(Path.home() / ".local" / "bin" / "aap-demo")
    candidates.append(
        Path(__file__).resolve().parents[3] / "aap-demo" / "aap-demo.sh"
    )
    candidates.append(Path("/workspaces/workspace/projects/aap-demo/aap-demo.sh"))

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path

    raise EnsureError(
        "aap-demo not found. Install from /workspaces/workspace/projects/aap-demo "
        "(./install.sh) or set AAP_DEMO_BIN."
    )


def aap_demo_cmd(bin_path: Path, *args: str) -> list[str]:
    if bin_path.suffix == ".sh":
        return ["bash", str(bin_path), *args]
    return [str(bin_path), *args]


def kubeconfig_ready() -> bool:
    if not KUBECONFIG_DEFAULT.is_file():
        return False
    try:
        subprocess.run(
            ["kubectl", "get", "ns"],
            env={**os.environ, "KUBECONFIG": str(KUBECONFIG_DEFAULT)},
            capture_output=True,
            check=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def platform_healthy() -> bool:
    return env_platform_healthy()


def parse_openshift_version(version: str) -> tuple[int, int]:
    match = re.match(r"^(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"Invalid OpenShift version: {version}")
    return int(match.group(1)), int(match.group(2))


def openshift_version_meets_minimum(installed: str, required: str) -> bool:
    return parse_openshift_version(installed) >= parse_openshift_version(required)


def get_installed_crc_openshift_version() -> str | None:
    if not shutil.which("crc"):
        return None
    try:
        result = subprocess.run(
            ["crc", "status", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    version = data.get("openshiftVersion", "")
    match = re.match(r"^(\d+\.\d+)", str(version))
    return match.group(1) if match else None


def get_crc_bundle_openshift_version() -> str | None:
    """Best-effort version from downloaded MicroShift CRC bundles."""
    cache = Path.home() / ".crc" / "cache"
    if not cache.is_dir():
        return None
    found: list[str] = []
    for bundle in cache.glob("crc_microshift_*.crcbundle"):
        match = re.search(r"(\d+\.\d+)", bundle.name)
        if match:
            found.append(match.group(1))
    if not found:
        return None
    return max(found, key=parse_openshift_version)


def effective_crc_version() -> str | None:
    """CRC_VERSION for aap-demo deploy: match the cluster or local CRC bundle.

    aap-demo defaults to requiring 4.22+, but that is a deploy-time check only.
    Passing the actual MicroShift version (e.g. 4.21) avoids false failures when
    the local CRC bundle is still 4.21. Override with AAP_E2E_CRC_VERSION or
    CRC_VERSION in the environment.
    """
    for key in ("AAP_E2E_CRC_VERSION", "CRC_VERSION"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return get_installed_crc_openshift_version() or get_crc_bundle_openshift_version()


def aap_demo_subprocess_env() -> dict[str, str]:
    """Environment for non-interactive aap-demo deploy.

    Skips sudo/keychain CA import by default (AAP_DEMO_TRUST_CA=false). The E2E
    harness uses aap_validate_certs=false against the gateway. Set
    AAP_E2E_TRUST_CA=true to allow aap-demo to prompt for sudo and trust the
    ingress CA in the OS store (browser use).
    """
    env = {
        **os.environ,
        "QUIET": "true",
        "KUBECONFIG": str(KUBECONFIG_DEFAULT),
        # Skip resource prompts in crc-create.sh (uses defaults when stdin is not a TTY)
        "CRC_CPUS": os.environ.get("AAP_E2E_CRC_CPUS", os.environ.get("CRC_CPUS", "8")),
        "CRC_MEMORY": os.environ.get(
            "AAP_E2E_CRC_MEMORY_MB",
            os.environ.get("CRC_MEMORY", str(16 * 1024)),
        ),
        "CRC_DISK": os.environ.get("AAP_E2E_CRC_DISK_GB", os.environ.get("CRC_DISK", "120")),
        "CRC_PV_SIZE": os.environ.get(
            "AAP_E2E_CRC_PV_SIZE_GB", os.environ.get("CRC_PV_SIZE", "70")
        ),
        "SKIP_TEMP_SWAP": "true",
        # Suppress aap-demo watch_aap clear/TUI when subprocess stdout is redirected.
        "TERM": "dumb",
    }
    crc_version = effective_crc_version()
    if crc_version:
        env["CRC_VERSION"] = crc_version
    if os.environ.get("AAP_E2E_TRUST_CA", "").lower() not in ("1", "true", "yes"):
        env["AAP_DEMO_TRUST_CA"] = "false"
    return env


def run_aap_demo(
    bin_path: Path,
    *args: str,
    env: dict[str, str],
    timeout: int,
    check: bool = True,
) -> int:
    cmd = aap_demo_cmd(bin_path, *args)
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(
        cmd,
        env=env,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        # Ansible modules must keep stdout clean for JSON (especially async tasks).
        stdout=subprocess.DEVNULL,
    )
    if check and result.returncode != 0:
        label = " ".join(args) if args else "command"
        raise EnsureError(f"aap-demo {label} failed with exit {result.returncode}")
    return result.returncode


def run_aap_demo_deploy(
    bin_path: Path,
    env: dict[str, str],
    timeout: int,
    poll_interval: int = 10,
) -> None:
    """Run aap-demo deploy and exit early when the AAP CR reports Failure.

    aap-demo's watch_aap loop only stops on Successful=True or a 60-minute
    timeout, so a wedged hub deployment (e.g. missing nfs-local-rwx) appears
    to hang forever.
    """
    cmd = aap_demo_cmd(bin_path, "deploy")
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        # aap-demo deploy prints a live TUI to stdout; async wrapper needs clean JSON.
        stdout=subprocess.DEVNULL,
    )
    start = time.monotonic()
    try:
        while True:
            returncode = proc.poll()
            if returncode is not None:
                if returncode != 0:
                    hint = deployment_failure_hint()
                    detail = f"\n{hint}" if hint else ""
                    raise DeployFailedError(
                        f"aap-demo deploy failed with exit {returncode}{detail}"
                    )
                return

            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                proc.kill()
                proc.wait(timeout=30)
                hint = deployment_failure_hint()
                detail = f"\n{hint}" if hint else ""
                raise DeployFailedError(
                    f"aap-demo deploy timed out after {int(elapsed)}s{detail}"
                )

            conditions = get_aap_conditions()
            if conditions and conditions.failure:
                proc.kill()
                proc.wait(timeout=30)
                hint = deployment_failure_hint()
                message = conditions.failure_message or "Failed"
                detail = f"\n{hint}" if hint else ""
                raise DeployFailedError(f"AAP deployment failed: {message}{detail}")

            time.sleep(poll_interval)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
        raise


def ensure(*, write_env: Path | str, timeout: int = DEPLOY_TIMEOUT_SEC) -> dict:
    write_env = Path(write_env)
    if platform_healthy():
        try:
            data = export_env()
            write_env_yaml(data, write_env)
            return data
        except RuntimeError as exc:
            print(
                f"Platform health check passed but env export failed ({exc}); "
                "running aap-demo deploy...",
                file=sys.stderr,
            )

    if not kubeconfig_ready() and not PULL_SECRET.is_file():
        raise EnsureError(
            "OpenShift pull secret required for first-time CRC setup. "
            f"Copy it to {PULL_SECRET} "
            "(see projects/aap-demo/README.md)."
        )

    bin_path = find_aap_demo()
    env = aap_demo_subprocess_env()

    if env.get("AAP_DEMO_TRUST_CA") == "false":
        print(
            "Skipping OS ingress CA trust (no sudo). "
            "Tests use aap_validate_certs=false. "
            "Set AAP_E2E_TRUST_CA=true to trust CA in the keychain.",
            file=sys.stderr,
        )

    crc_version = env.get("CRC_VERSION")
    if crc_version:
        print(
            f"Using MicroShift/CRC version {crc_version} for aap-demo deploy check "
            f"(set AAP_E2E_CRC_VERSION to override).",
            file=sys.stderr,
        )
    else:
        print(
            "No local CRC version detected; aap-demo will apply its default "
            "CRC_VERSION check.",
            file=sys.stderr,
        )

    # Bring CRC up before NFS/deploy when the API is unreachable (stopped or missing).
    if not kubeconfig_ready():
        print(
            "Cluster API unreachable — starting/creating CRC via aap-demo...",
            file=sys.stderr,
        )
        # start handles Stopped; create handles first-time / missing VM.
        # deploy also starts CRC, but an explicit bring-up fails faster with clearer logs.
        start_rc = run_aap_demo(bin_path, "start", env=env, timeout=timeout, check=False)
        if not kubeconfig_ready():
            if start_rc != 0:
                print(
                    "aap-demo start did not bring the API up; trying aap-demo create...",
                    file=sys.stderr,
                )
            run_aap_demo(bin_path, "create", env=env, timeout=timeout)
        if not kubeconfig_ready():
            raise EnsureError(
                "CRC/API still unreachable after aap-demo start/create. "
                "Check: crc status && aap-demo start"
            )

    ensure_nfs_storage_class(find_aap_demo_root(bin_path))

    try:
        items = list_aap_crs()
        if items:
            print(
                f"AAP CR present: {cr_status_summary(pick_aap_cr(items))}",
                file=sys.stderr,
            )
        else:
            print("No AAP CR in cluster; running aap-demo deploy...", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - status hint only
        print(f"Could not read AAP CR status: {exc}", file=sys.stderr)

    max_deploy_attempts = int(os.environ.get("AAP_E2E_DEPLOY_ATTEMPTS", "2"))
    for attempt in range(1, max_deploy_attempts + 1):
        conditions = get_aap_conditions()
        if conditions and conditions.failure:
            print(
                "AAP CR is in Failed state; running aap-demo clean before redeploy...",
                file=sys.stderr,
            )
            run_aap_demo(bin_path, "clean", env=env, timeout=600)

        try:
            run_aap_demo_deploy(bin_path, env=env, timeout=timeout)
            break
        except DeployFailedError as exc:
            if (
                attempt < max_deploy_attempts
                and is_recoverable_deploy_failure(exc.message)
            ):
                print(
                    "Recoverable gateway rollout race detected; "
                    "cleaning and redeploying once...",
                    file=sys.stderr,
                )
                run_aap_demo(bin_path, "clean", env=env, timeout=600)
                continue
            raise EnsureError(exc.message) from exc

    print("Waiting for AAP CR Successful=True and gateway ping...", file=sys.stderr)
    wait_until_platform_healthy(timeout=timeout, poll_interval=15)
    data = export_env()
    wait_ping(data["aap_hostname"], data["aap_username"], data["aap_password"])
    write_env_yaml(data, write_env)
    return data
