# aap-configuration-e2e

Local **Molecule** end-to-end tests for `infra.aap_configuration`, using [aap-demo](https://github.com/RedHatOfficial/aap-demo) to run AAP on CRC (OpenShift Local).

The CLI installs whichever **version** of the collection you point at (local path, PR, or git ref), then runs Molecule. **Molecule owns CRC/AAP and the test.**

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for diagrams, teardown behavior, and where this repo should live relative to `infra.aap_configuration`.

## Test a collection version (main use case)

```bash
make setup

# Local checkout
.venv/bin/python -m aap_configuration_e2e test --path ~/workspace/forks/infra.aap_configuration

# GitHub PR (requires `gh` auth)
.venv/bin/python -m aap_configuration_e2e test --pr 123

# Branch or tag on any fork
.venv/bin/python -m aap_configuration_e2e test --repo redhat-cop/infra.aap_configuration --ref devel
.venv/bin/python -m aap_configuration_e2e test --repo myuser/infra.aap_configuration --ref my-feature-branch

# Deeper scenario
.venv/bin/python -m aap_configuration_e2e test --path ... --scenario platform

# Reuse running CRC+AAP (only re-install collection + converge)
.venv/bin/python -m aap_configuration_e2e test --path ... --skip-provision
```

Each `test` run: (1) installs certified deps + SUT into `.cache/collections`, (2) runs `molecule test`. That is how you validate a PR or branch without merging it.

| Source | Flag |
|--------|------|
| Local directory | `--path /path/to/infra.aap_configuration` |
| Pull request | `--pr <number>` (optional `--repo owner/name`, default `redhat-cop/infra.aap_configuration`) |
| Git ref | `--repo owner/name --ref <branch-or-tag>` |
| Default | `--path` if `~/workspace/forks/infra.aap_configuration` exists, else upstream `devel` |

## Molecule lifecycle

| Phase | Responsibility |
|-------|----------------|
| **create** | CRC if configured / not reachable, then AAP; write `.cache/aap-env.yml` |
| **prepare** | Assert env file + connection vars |
| **converge** | Apply scenario config via `infra.aap_configuration.dispatch` |
| **verify** | Assert objects via gateway / controller APIs |
| **cleanup** | Remove test objects (`state: absent`) — not CRC/AAP. **Skipped** when `AAP_E2E_DESTROY_*` is set (platform teardown makes API cleanup unnecessary). |
| **destroy** | Optionally tear down AAP and/or CRC (`AAP_E2E_DESTROY_*`; default leave up) |

`molecule test` sequence:

```text
destroy → syntax → create → prepare → converge → verify → cleanup → destroy
```

The leading **destroy** clears Molecule’s “already created” flag so **create always runs**. With defaults it does not delete CRC/AAP.

```bash
molecule create    # CRC (if needed) + AAP
molecule converge  # apply config
molecule verify    # validate expected objects
molecule cleanup   # delete test objects
molecule destroy   # optional AAP/CRC teardown
```

## Quick start

```bash
cd ~/workspace/projects/aap-configuration-e2e
make setup
make test-smoke COLLECTION_PATH=~/workspace/forks/infra.aap_configuration
```

## Platform variables

**create** (`roles/aap_e2e_platform`):

| Variable | Env | Default | Meaning |
|----------|-----|---------|---------|
| `aap_e2e_skip_provision` | `AAP_E2E_SKIP_PROVISION` | `false` | Skip CRC/AAP; export env from a running platform |
| `aap_e2e_provision_crc` | — | `true` | `aap-demo create` when cluster unreachable |
| `aap_e2e_provision_aap` | — | `true` | Deploy/heal AAP when unhealthy |

**destroy** (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#cleanup-vs-destroy-platform-teardown)):

| Variable | Env | Default | Meaning |
|----------|-----|---------|---------|
| `aap_e2e_destroy_aap` | `AAP_E2E_DESTROY_AAP` | `false` | `aap-demo clean` (delete AAP namespace); skipped if CRC destroy is also requested |
| `aap_e2e_destroy_crc` | `AAP_E2E_DESTROY_CRC` | `false` | `aap-demo destroy` (delete CRC VM) |

When either destroy flag is set, **cleanup skips test-object API deletion** so `make destroy-all` does not fail against a dead platform.

```bash
# Molecule phases (uses collection already in .cache/collections)
make              # show all targets
make create       # always re-runs create (starts CRC if stopped)
make converge verify
make cleanup      # remove test objects only (AAP must be up)

# Platform teardown
make destroy-aap  # aap-demo clean — AAP gone, CRC stays
make destroy-crc  # aap-demo destroy — CRC VM gone
make destroy-all  # destroy CRC only (skips clean + config cleanup)

# Full test then tear down AAP
AAP_E2E_DESTROY_AAP=true .venv/bin/python -m aap_configuration_e2e test --path ...
```

## Prerequisites

1. **aap-demo** installed or at `projects/aap-demo`.
2. Pull secret at `~/.aap-demo/pull-secret.txt` (first CRC create).
3. Galaxy token at `~/.aap-demo/galaxy-token`.
4. `kubectl` on PATH; `gh` only for `--pr`.
5. **AAP subscription manifest** (`.zip`). Molecule **prepare** checks Controller `license_info`; if unlicensed it applies the first existing path from:
   - `AAP_E2E_LICENSE_MANIFEST`
   - `~/.aap-demo/manifest.zip`
   - `~/.aap-demo/subscription-manifest.zip`
   - `.cache/manifest.zip`
   Without a license, host create returns HTTP 403 `License is missing.`

## Scenarios

| Scenario | Coverage |
|----------|----------|
| `smoke` | Thin gate: org/team, project/inventory/host/JT, hub namespace, EDA credential |
| `platform` | Deep regression: many dispatch roles with **multiple object variants** and rich option fields |

Config: `config/<scenario>/` → org **`aap-config-e2e`**.

### Platform coverage matrix

Dispatch roles exercised by platform config (create/update; no launches/syncs/settings):

| Area | Vars / roles | Variants (approx) |
|------|----------------|-------------------|
| Gateway | `aap_organizations`, `aap_teams`, `aap_user_accounts`, `aap_applications`, `gateway_role_user_assignments`, `gateway_role_team_assignments`, `gateway_settings` | 2 teams, 2 users, 2 apps, 3 user RBAC, 2 team RBAC; safe settings (basic auth on, no proxy/URL) |
| Controller foundation | `controller_credential_types`, `controller_credentials`, `controller_execution_environments`, `controller_labels`, `controller_notifications`, `controller_settings` | custom type + 6 creds, 2 EEs, 3 labels, email+webhook; safe settings (task env marker, activity stream, schedule max) |
| Controller content | `controller_projects`, `controller_inventories`, `controller_hosts`, `controller_groups`, `controller_bulk_hosts`, `controller_inventory_sources` | 3 projects, 2 inventories, 3 hosts, nested groups, bulk hosts, SCM inv source |
| Controller jobs | `controller_templates`, `controller_workflows`, `controller_schedules` | fixed/survey/check/compat JTs; linear/rich/compat workflows; JT+WF schedules |
| Hub | `hub_namespaces`, `hub_ee_registries`, `hub_ee_repositories`, `hub_collection_remotes`, `hub_collection_repositories` | 2 namespaces, registry+repo (no sync), remote+repo (no sync) |
| Controller capacity | `controller_instance_groups` | empty IG (0% / min 0; does not claim control plane) |
| EDA | `eda_credential_types`, `eda_credentials`, `eda_projects`, `eda_decision_environments`, `eda_event_streams` | custom type, 4 creds, 2 projects, 2 DEs, event stream |

**Intentionally excluded from platform** (cluster-breaking or side-effect): gateway authenticators/services/routes and non-safe settings (proxy URL, password policy, disabling basic auth); controller instances/launches/credential_input_sources and non-safe settings (LDAP, `TOWER_URL_BASE`, log aggregators, capacity); hub sync/publish/index; EDA rulebook activations. Candidate for a future `launch` / `infra_sensitive` scenario.

**Settings note:** platform applies only a small “safe” subset via `config/platform/{controller,gateway}_settings.yml`. Cleanup re-applies the same values (settings are not deleted).

## CLI (thin)

| Command | Role |
|---------|------|
| `test` | `install_sut` (path / PR / git ref) → `molecule test` |
| `ensure` | Ad-hoc CRC+AAP (same logic create uses) |
| `env` | Export `.cache/aap-env.yml` only |

## Repo layout vs `infra.aap_configuration`

Keep this harness **separate** from the collection: it carries CRC/aap-demo weight and installs arbitrary SUT versions into `.cache/collections` per run. The collection keeps fast `roles/*/tests/` playbooks; this repo owns platform provisioning, Molecule, and E2E config. Config *could* move to `infra.aap_configuration/tests/e2e/` later with the harness loading it via env — details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#where-should-this-code-live).

## CRC notes

- MicroShift preset; harness does not destroy CRC just to upgrade OpenShift.
- Non-interactive create; override with `AAP_E2E_CRC_*` / `AAP_E2E_CRC_VERSION`.
- Default `AAP_E2E_TRUST_CA=false` avoids sudo prompts; tests use `aap_validate_certs=false`.

## Unit tests

```bash
make test-unit
```

## Troubleshooting

**Wrong Python / cannot import aap_configuration_e2e** — Ansible was using a global interpreter (e.g. `~/workspace/ansible/bin/python`). `make` now forces `.venv/bin` on `PATH` and sets `ANSIBLE_PYTHON_INTERPRETER`. If you still see the global Python, run `make setup` then `make create` (not bare `molecule`).

**`ModuleNotFoundError: No module named 'requests'` on converge** — `ansible.platform` gateway modules spawn a manager subprocess that needs `requests` in the project venv. Run `make install` or `make setup`, then `make converge` again.

**Create skipped / CRC stayed off** — Molecule create `--limit`s to the platform hostname. The platform is named `localhost` so it matches the playbooks. Create checks `crc status` and runs `aap-demo start` when Stopped.

**Hub Pending / deploy hung** — harness installs NFS SC, cleans Failed CRs, fails fast on Failure.

**Gateway pod not found** — one auto retry (`clean` + redeploy); `AAP_E2E_DEPLOY_ATTEMPTS=1` disables.

**`You don't have permission to POST to /api/controller/v2/hosts/ (HTTP 403)`** — Almost always an unlicensed Controller, not RBAC. Put a Red Hat AAP subscription manifest at `~/.aap-demo/manifest.zip` (or `AAP_E2E_LICENSE_MANIFEST=/path/to/manifest.zip`) and re-run `make converge`; prepare will apply it automatically. Confirm with:

```bash
curl -sk -u admin:"$(yq -r .aap_password .cache/aap-env.yml)" \
  "https://$(yq -r .aap_hostname .cache/aap-env.yml)/api/controller/v2/config/" | jq .license_info
```
