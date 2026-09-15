"""Local Molecule E2E harness for infra.aap_configuration against aap-demo AAP."""

from pathlib import Path

ORG_NAME = "aap-config-e2e"
TEAM_NAME = "aap-config-e2e-team"
PROJECT_NAME = "aap-config-e2e-project"
INVENTORY_NAME = "aap-config-e2e-inventory"
HOST_NAME = "localhost"
JT_NAME = "aap-config-e2e-job-template"
HUB_NS_NAME = "aap_config_e2e"
EDA_CRED_NAME = "aap-config-e2e-scm"
AAP_DEMO_NS_DEFAULT = "aap-operator"
PULL_SECRET = Path.home() / ".aap-demo" / "pull-secret.txt"
GALAXY_TOKEN_FILE = Path.home() / ".aap-demo" / "galaxy-token"
KUBECONFIG_DEFAULT = Path.home() / ".aap-demo" / "kubeconfig.microshift"
ENV_YAML_NAME = "aap-env.yml"
DEPLOY_TIMEOUT_SEC = 5400
PING_RETRIES = 60
PING_DELAY_SEC = 10
DEFAULT_COLLECTION_REPO = "redhat-cop/infra.aap_configuration"
