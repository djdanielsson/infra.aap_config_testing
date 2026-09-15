"""Install infra.aap_configuration (system under test) into .cache/collections."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from aap_configuration_e2e import DEFAULT_COLLECTION_REPO
from aap_configuration_e2e.galaxy import galaxy_env, install_certified_deps


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def collections_path() -> Path:
    return project_root() / ".cache" / "collections"


def install_from_path(src: Path) -> None:
    src = src.resolve()
    if not (src / "galaxy.yml").is_file():
        raise SystemExit(f"Not a collection directory (no galaxy.yml): {src}")

    root = project_root()
    dest = collections_path()
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        build_dir = Path(tmp)
        result = subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "build",
                str(src),
                "--output-path",
                str(build_dir),
            ],
            cwd=root,
            env=galaxy_env(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            raise SystemExit(f"ansible-galaxy collection build failed for {src}")

        tarballs = list(build_dir.glob("*.tar.gz"))
        if not tarballs:
            raise SystemExit("ansible-galaxy collection build produced no tarball")

        result = subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "install",
                str(tarballs[0]),
                "-p",
                str(dest),
                "--force",
            ],
            cwd=root,
            env=galaxy_env(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            raise SystemExit("ansible-galaxy collection install failed")


def install_from_git(repo: str, ref: str) -> None:
    dest = collections_path()
    dest.mkdir(parents=True, exist_ok=True)
    url = f"git+https://github.com/{repo}.git,{ref}"
    result = subprocess.run(
        [
            "ansible-galaxy",
            "collection",
            "install",
            url,
            "-p",
            str(dest),
            "--force",
        ],
        cwd=project_root(),
        env=galaxy_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"ansible-galaxy collection install failed for {url}")


def install_from_pr(number: int, repo: str = DEFAULT_COLLECTION_REPO) -> None:
    if not shutil.which("gh"):
        raise SystemExit("Install GitHub CLI (gh) to use --pr")

    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "headRepository,headRepositoryOwner,headRefName",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"gh pr view failed for PR #{number} on {repo}")

    data = json.loads(result.stdout)
    owner = data["headRepositoryOwner"]["login"]
    name = data["headRepository"]["name"]
    ref = data["headRefName"]
    install_from_git(f"{owner}/{name}", ref)


def install_sut(
    *,
    path: Path | None = None,
    pr: int | None = None,
    repo: str = DEFAULT_COLLECTION_REPO,
    ref: str = "devel",
) -> Path:
    dest = collections_path()
    install_certified_deps(dest, project_root())

    if path is not None:
        install_from_path(path)
    elif pr is not None:
        install_from_pr(pr, repo)
    else:
        install_from_git(repo, ref)

    return dest
