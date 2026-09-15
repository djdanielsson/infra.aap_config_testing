#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: aap_e2e_export_env
short_description: Export AAP gateway connection vars from a running cluster
options:
  write_env:
    description: Path to write aap-env.yml.
    type: path
    required: true
"""

import traceback
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule, missing_required_lib

try:
    from aap_configuration_e2e.env import export_env, write_env_yaml
except ImportError:
    export_env = None
    write_env_yaml = None


def main():
    module = AnsibleModule(
        argument_spec={
            "write_env": {"type": "path", "required": True},
        },
    )

    if export_env is None:
        import sys

        module.fail_json(
            msg=(
                f"{missing_required_lib('aap_configuration_e2e')} "
                f"(interpreter={sys.executable}). "
                "Use the project .venv: make setup && make create"
            ),
        )

    try:
        data = export_env()
        write_env_yaml(data, Path(module.params["write_env"]))
        module.exit_json(changed=False, env=data)
    except Exception as exc:  # noqa: BLE001
        module.fail_json(msg=str(exc), exception=traceback.format_exc())


if __name__ == "__main__":
    main()
