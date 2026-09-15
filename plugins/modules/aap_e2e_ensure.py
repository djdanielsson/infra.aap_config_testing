#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: aap_e2e_ensure
short_description: Ensure CRC and AAP are running via aap-demo
description:
  - Provisions NFS storage if needed, deploys AAP when not healthy, and writes
    connection variables for Molecule converge/verify playbooks.
options:
  write_env:
    description: Path to write aap-env.yml (gateway URL, credentials).
    type: path
    required: true
  timeout:
    description: Maximum seconds for aap-demo deploy.
    type: int
    default: 5400
  provision_aap:
    description: When false, only refresh env if the platform is already healthy.
    type: bool
    default: true
"""

EXAMPLES = r"""
- name: Ensure AAP platform
  aap_e2e_ensure:
    write_env: "{{ playbook_dir }}/../.cache/aap-env.yml"
    timeout: 5400
"""

RETURN = r"""
env:
  description: Exported AAP connection variables.
  type: dict
  returned: success
changed:
  description: Whether deploy or env export was performed.
  type: bool
"""

import traceback
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule, missing_required_lib

try:
    from aap_configuration_e2e.ensure_aap import ensure
    from aap_configuration_e2e.env import export_env, platform_healthy, write_env_yaml
    from aap_configuration_e2e.errors import EnsureError
except ImportError:
    ensure = None
    export_env = None
    platform_healthy = None
    write_env_yaml = None
    EnsureError = Exception  # type: ignore[misc, assignment]


def main():
    module = AnsibleModule(
        argument_spec={
            "write_env": {"type": "path", "required": True},
            "timeout": {"type": "int", "default": 5400},
            "provision_aap": {"type": "bool", "default": True},
        },
    )

    if ensure is None:
        import sys

        module.fail_json(
            msg=(
                f"{missing_required_lib('aap_configuration_e2e')} "
                f"(interpreter={sys.executable}). "
                "Use the project .venv: make setup && make create"
            ),
        )

    write_env = Path(module.params["write_env"])
    timeout = module.params["timeout"]
    provision_aap = module.params["provision_aap"]

    if not provision_aap:
        if not platform_healthy():
            module.fail_json(
                msg="AAP is not healthy and provision_aap=false",
            )
        try:
            data = export_env()
            write_env_yaml(data, write_env)
        except Exception as exc:  # noqa: BLE001 - surface to ansible
            module.fail_json(msg=str(exc), exception=traceback.format_exc())
        module.exit_json(changed=False, env=data)

    was_healthy = platform_healthy()
    try:
        data = ensure(write_env=write_env, timeout=timeout)
    except EnsureError as exc:
        module.fail_json(msg=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface to ansible
        module.fail_json(msg=str(exc), exception=traceback.format_exc())

    # exit_json must not run inside try/except — it raises SystemExit(0).
    module.exit_json(changed=not was_healthy, env=data)


if __name__ == "__main__":
    main()
