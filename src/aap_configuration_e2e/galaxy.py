"""Galaxy token handling and certified collection install."""

import os
import subprocess
import sys
from pathlib import Path

from aap_configuration_e2e import GALAXY_TOKEN_FILE


def read_galaxy_token() -> str | None:
    if not GALAXY_TOKEN_FILE.is_file():
        return None
    token = GALAXY_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return token or None


def galaxy_env(base: dict | None = None) -> dict:
    env = dict(base or os.environ)
    token = read_galaxy_token()
    if token:
        env["ANSIBLE_GALAXY_SERVER_CERTIFIED_TOKEN"] = token
        env["ANSIBLE_GALAXY_SERVER_VALIDATED_TOKEN"] = token
    return env


def install_certified_deps(collections_path: Path, project_root: Path) -> None:
    collections_path.mkdir(parents=True, exist_ok=True)
    req = project_root / "collections" / "requirements.yml"
    result = subprocess.run(
        [
            "ansible-galaxy",
            "collection",
            "install",
            "-r",
            str(req),
            "-p",
            str(collections_path),
            "--force-with-deps",
        ],
        cwd=project_root,
        env=galaxy_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(
            "Certified collections failed to install. Put a Red Hat offline token in "
            "~/.aap-demo/galaxy-token (see projects/aap-demo/docs/collection-authentication.md)."
        )
