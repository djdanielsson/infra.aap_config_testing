PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
SCENARIO ?= smoke
COLLECTION_PATH ?= /workspaces/workspace/forks/infra.aap_configuration
AAP_CONFIGURATION_TEMPLATE_PATH ?= $(CURDIR)/../../forks/aap_configuration_template
AAP_CONFIG_ENV ?= dev

MOLECULE := $(BIN)/molecule
# Prefer project venv for ansible-playbook + module interpreter (custom modules
# import aap_configuration_e2e from the venv, not a global Ansible Python).
ANSIBLE_ENV := \
	PATH=$(CURDIR)/$(BIN):$${PATH} \
	ANSIBLE_CONFIG=$(CURDIR)/ansible.cfg \
	ANSIBLE_COLLECTIONS_PATH=$(CURDIR)/.cache/collections \
	ANSIBLE_PYTHON_INTERPRETER=$(CURDIR)/$(BIN)/python \
	AAP_CONFIGURATION_E2E_PYTHON=$(CURDIR)/$(BIN)/python

.DEFAULT_GOAL := help

.PHONY: help setup install test-unit test-smoke test-platform \
	create converge converge-template verify cleanup destroy \
	destroy-aap destroy-crc destroy-all reset \
	molecule-create molecule-converge molecule-verify molecule-cleanup \
	molecule-destroy molecule-destroy-aap molecule-destroy-crc molecule-destroy-all molecule-reset

help:
	@echo "aap-configuration-e2e — Molecule E2E harness"
	@echo ""
	@echo "Usage: make <target> [SCENARIO=smoke|platform]"
	@echo ""
	@echo "Setup"
	@echo "  setup                 Create .venv and install package + Molecule"
	@echo "  install               Reinstall package into .venv (run after src/ changes)"
	@echo "  test-unit             Run pytest unit tests"
	@echo ""
	@echo "Full test (install collection + molecule test)"
	@echo "  test-smoke            E2E smoke scenario"
	@echo "  test-platform         E2E platform scenario"
	@echo ""
	@echo "Molecule lifecycle (CRC/AAP + config)"
	@echo "  create                Reset Molecule state, then create CRC (if needed/stopped) + AAP"
	@echo "  converge              Apply scenario config via infra.aap_configuration"
	@echo "  converge-template     Apply aap_configuration_template via dispatch (sanity check)"
	@echo "  verify                Assert objects via gateway/controller APIs"
	@echo "  cleanup               Remove test objects only (not CRC/AAP)"
	@echo "  destroy               Molecule destroy (no-op for CRC/AAP unless DESTROY_* set)"
	@echo "  reset                 Clear Molecule ephemeral state (does not touch CRC/AAP)"
	@echo ""
	@echo "Platform teardown"
	@echo "  destroy-aap           Remove AAP (aap-demo clean); keep CRC"
	@echo "  destroy-crc           Destroy CRC VM (aap-demo destroy)"
	@echo "  destroy-all           Remove AAP and CRC"
	@echo ""
	@echo "Env overrides"
	@echo "  AAP_E2E_SKIP_PROVISION=true   create: only export env from running platform"
	@echo "  AAP_E2E_DESTROY_AAP=true      destroy: tear down AAP"
	@echo "  AAP_E2E_DESTROY_CRC=true      destroy: tear down CRC"
	@echo "  AAP_E2E_LICENSE_MANIFEST=...  subscription manifest .zip for prepare"
	@echo "  SCENARIO=platform|template    select Molecule scenario (default: smoke)"
	@echo "  COLLECTION_PATH=...           path for test-smoke / test-platform"
	@echo "  AAP_CONFIGURATION_TEMPLATE_PATH=...  template repo for converge-template"
	@echo "  AAP_CONFIG_ENV=dev|qa|prod    template config/<env> (default: dev)"
	@echo ""
	@echo "Examples"
	@echo "  make create"
	@echo "  make converge verify"
	@echo "  make destroy-aap"
	@echo "  make destroy-crc"
	@echo "  make destroy-all"
	@echo "  AAP_E2E_SKIP_PROVISION=true make create converge"
	@echo "  AAP_E2E_LICENSE_MANIFEST=~/manifest.zip make converge"

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e ".[test]"

# Reinstall src/ into .venv so custom modules pick up ensure_aap changes.
install:
	$(BIN)/pip install -e ".[test]"

test-unit:
	$(BIN)/pytest -q

test-smoke:
	$(BIN)/python -m aap_configuration_e2e test --path $(COLLECTION_PATH) --scenario smoke

test-platform:
	$(BIN)/python -m aap_configuration_e2e test --path $(COLLECTION_PATH) --scenario platform

# Force create playbook to run: Molecule otherwise skips when state says created.
create molecule-create: install reset
	$(ANSIBLE_ENV) $(MOLECULE) create -s $(SCENARIO)

converge molecule-converge: install
	$(ANSIBLE_ENV) $(MOLECULE) converge -s $(SCENARIO)

converge-template: install
	$(ANSIBLE_ENV) \
		AAP_CONFIGURATION_TEMPLATE_PATH=$(AAP_CONFIGURATION_TEMPLATE_PATH) \
		AAP_CONFIG_ENV=$(AAP_CONFIG_ENV) \
		ANSIBLE_LIBRARY=$(CURDIR)/plugins/modules:$(AAP_CONFIGURATION_TEMPLATE_PATH)/plugins/modules \
		ANSIBLE_ACTION_PLUGINS=$(AAP_CONFIGURATION_TEMPLATE_PATH)/plugins/action \
		$(MOLECULE) converge -s template

verify molecule-verify: install
	$(ANSIBLE_ENV) $(MOLECULE) verify -s $(SCENARIO)

cleanup molecule-cleanup:
	$(ANSIBLE_ENV) $(MOLECULE) cleanup -s $(SCENARIO)

destroy molecule-destroy:
	$(ANSIBLE_ENV) $(MOLECULE) destroy -s $(SCENARIO)

destroy-aap molecule-destroy-aap:
	$(ANSIBLE_ENV) AAP_E2E_DESTROY_AAP=true $(MOLECULE) destroy -s $(SCENARIO)

destroy-crc molecule-destroy-crc:
	$(ANSIBLE_ENV) AAP_E2E_DESTROY_CRC=true $(MOLECULE) destroy -s $(SCENARIO)

destroy-all molecule-destroy-all:
	$(ANSIBLE_ENV) AAP_E2E_DESTROY_AAP=true AAP_E2E_DESTROY_CRC=true $(MOLECULE) destroy -s $(SCENARIO)

# Clears Molecule "instances already created" flag without touching CRC/AAP.
reset molecule-reset:
	$(ANSIBLE_ENV) $(MOLECULE) reset -s $(SCENARIO) || \
		$(ANSIBLE_ENV) $(MOLECULE) destroy -s $(SCENARIO)
