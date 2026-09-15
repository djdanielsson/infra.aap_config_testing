"""Unit tests for install_collection.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

from aap_configuration_e2e.install_collection import install_from_pr


def test_install_from_pr_parses_gh_json():
    gh_output = json.dumps(
        {
            "headRepositoryOwner": {"login": "someuser"},
            "headRepository": {"name": "infra.aap_configuration"},
            "headRefName": "fix-thing",
        }
    )

    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=gh_output, stderr="")
            with patch(
                "aap_configuration_e2e.install_collection.install_from_git"
            ) as mock_git:
                install_from_pr(42, "redhat-cop/infra.aap_configuration")
                mock_git.assert_called_once_with(
                    "someuser/infra.aap_configuration", "fix-thing"
                )


def test_install_from_pr_requires_gh():
    with patch("shutil.which", return_value=None):
        with pytest.raises(SystemExit) as exc:
            install_from_pr(1)
        assert "gh" in str(exc.value).lower()
