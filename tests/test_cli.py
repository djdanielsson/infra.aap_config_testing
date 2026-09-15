"""Unit tests for cli.py."""

from unittest.mock import MagicMock, patch

from aap_configuration_e2e.cli import main


def test_test_command_skips_provision_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "collections").mkdir()
    (tmp_path / "collections" / "requirements.yml").write_text(
        "---\ncollections: []\n", encoding="utf-8"
    )

    with patch("aap_configuration_e2e.cli.project_root", return_value=tmp_path):
        with patch("aap_configuration_e2e.cli.install_sut"):
            with patch("aap_configuration_e2e.cli.ensure") as mock_ensure:
                with patch("aap_configuration_e2e.cli._run_molecule", return_value=0) as mock_mol:
                    rc = main(
                        [
                            "test",
                            "--path",
                            str(tmp_path / "collection"),
                            "--skip-provision",
                        ]
                    )

    mock_ensure.assert_not_called()
    mock_mol.assert_called_once_with("smoke", True)
    assert rc == 0


def test_test_command_runs_molecule_without_cli_ensure(tmp_path):
    with patch("aap_configuration_e2e.cli.install_sut"):
        with patch("aap_configuration_e2e.cli.ensure") as mock_ensure:
            with patch("aap_configuration_e2e.cli._run_molecule", return_value=0) as mock_mol:
                main(["test", "--path", "/tmp/collection"])

    mock_ensure.assert_not_called()
    mock_mol.assert_called_once_with("smoke", False)
