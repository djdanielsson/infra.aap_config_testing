"""Errors raised by the E2E harness (safe for Ansible modules)."""


class EnsureError(Exception):
    """Platform ensure failed (CRC/AAP deploy, env export, etc.)."""
