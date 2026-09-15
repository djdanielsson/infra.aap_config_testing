"""CLI for running Molecule E2E tests."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from aap_configuration_e2e import DEFAULT_COLLECTION_REPO, ENV_YAML_NAME
from aap_configuration_e2e.ensure_aap import ensure
from aap_configuration_e2e.errors import EnsureError
from aap_configuration_e2e.env import export_env, write_env_yaml
from aap_configuration_e2e.galaxy import galaxy_env
from aap_configuration_e2e.install_collection import collections_path, install_sut, project_root

DEFAULT_LOCAL_PATH = Path("/workspaces/workspace/forks/infra.aap_configuration")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aap-configuration-e2e",
        description="Local Molecule E2E harness for infra.aap_configuration",
    )
    sub = parser.add_subparsers(dest="command")

    test_p = sub.add_parser("test", help="Install collection and run Molecule scenario")
    src = test_p.add_mutually_exclusive_group()
    src.add_argument("--path", type=Path, help="Local collection checkout path")
    src.add_argument("--pr", type=int, help="GitHub PR number")
    src.add_argument("--repo", default=DEFAULT_COLLECTION_REPO, help="GitHub repo owner/name")
    test_p.add_argument(
        "--ref",
        default="devel",
        help="Git ref when using --repo (default: devel)",
    )
    test_p.add_argument(
        "--scenario",
        choices=["smoke", "platform"],
        default="smoke",
        help="Molecule scenario (default: smoke)",
    )
    test_p.add_argument(
        "--skip-provision",
        action="store_true",
        help="Set AAP_E2E_SKIP_PROVISION=1 for Molecule create (no CRC/AAP changes)",
    )

    ensure_p = sub.add_parser("ensure", help="Ensure CRC+AAP via aap-demo and write env file")
    ensure_p.add_argument(
        "--write-env",
        type=Path,
        default=None,
        help="Path for aap-env.yml",
    )
    ensure_p.add_argument("--timeout-seconds", type=int, default=5400)

    env_p = sub.add_parser("env", help="Export AAP env from running cluster (no deploy)")
    env_p.add_argument("--write-env", type=Path, default=None)

    return parser


def _default_env_path() -> Path:
    return project_root() / ".cache" / ENV_YAML_NAME


def _run_molecule(scenario: str, skip_provision: bool) -> int:
    root = project_root()
    molecule_bin = Path(sys.executable).parent / "molecule"
    if not molecule_bin.is_file():
        molecule_bin = Path("molecule")

    env = galaxy_env()
    coll = collections_path()
    existing = os.environ.get("ANSIBLE_COLLECTIONS_PATH", "")
    env["ANSIBLE_COLLECTIONS_PATH"] = (
        f"{coll}:{existing}" if existing else str(coll)
    )
    env["ANSIBLE_CONFIG"] = str(root / "ansible.cfg")
    # Custom modules import aap_configuration_e2e from this venv — force that
    # interpreter for ansible-playbook and target modules (not a global Ansible Python).
    env["AAP_CONFIGURATION_E2E_PYTHON"] = sys.executable
    env["ANSIBLE_PYTHON_INTERPRETER"] = sys.executable
    venv_bin = str(Path(sys.executable).parent)
    env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', os.environ.get('PATH', ''))}"
    if skip_provision:
        env["AAP_E2E_SKIP_PROVISION"] = "1"

    return subprocess.run(
        [str(molecule_bin), "test", "-s", scenario],
        cwd=root,
        env=env,
    ).returncode


def _resolve_test_source(args: argparse.Namespace) -> tuple[Path | None, int | None, str, str]:
    if args.path is not None:
        return args.path, None, args.repo, args.ref
    if args.pr is not None:
        return None, args.pr, args.repo, args.ref
    if DEFAULT_LOCAL_PATH.is_dir():
        return DEFAULT_LOCAL_PATH, None, args.repo, args.ref
    return None, None, args.repo, args.ref


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] not in ("test", "ensure", "env"):
        argv = ["test", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "ensure":
        write_env = args.write_env or _default_env_path()
        try:
            ensure(write_env=write_env, timeout=args.timeout_seconds)
        except EnsureError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Wrote {write_env}")
        return 0

    if args.command == "env":
        write_env = args.write_env or _default_env_path()
        data = export_env()
        write_env_yaml(data, write_env)
        print(f"Wrote {write_env}")
        return 0

    path, pr, repo, ref = _resolve_test_source(args)
    install_sut(path=path, pr=pr, repo=repo, ref=ref)

    if args.skip_provision:
        print(
            "AAP_E2E_SKIP_PROVISION=1 — Molecule create will not provision CRC/AAP",
            file=sys.stderr,
        )

    return _run_molecule(args.scenario, args.skip_provision)


if __name__ == "__main__":
    raise SystemExit(main())
