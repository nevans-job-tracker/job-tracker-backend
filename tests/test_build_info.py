"""Reporting which build is running (KAN-63)."""

import pytest

from app import build, main


class TestReadBuildInfo:
    def _write(self, tmp_path, text):
        target = tmp_path / "build-info"
        target.write_text(text, encoding="utf-8")
        return str(target)

    def test_reads_the_stamped_values(self, tmp_path):
        path = self._write(tmp_path, "sha=575e82f\nbranch=develop\n")
        assert build.read_build_info(path) == {
            "sha": "575e82f",
            "branch": "develop",
        }

    def test_a_missing_file_is_unknown_rather_than_an_error(self, tmp_path):
        """Development has no stamp. A version banner must never be the reason
        the service will not start."""
        assert build.read_build_info(str(tmp_path / "absent")) == {
            "sha": "unknown",
            "branch": "unknown",
        }

    def test_a_directory_in_place_of_the_file_is_also_unknown(self, tmp_path):
        # OSError rather than FileNotFoundError, which is why the except is
        # the broader one.
        assert build.read_build_info(str(tmp_path))["sha"] == "unknown"

    def test_ignores_blanks_comments_and_unknown_keys(self, tmp_path):
        path = self._write(
            tmp_path,
            "\n# written by job-tracker-backend.service\nsha=abc1234\n"
            "built_by=someone\nbranch=main\n",
        )
        assert build.read_build_info(path) == {"sha": "abc1234", "branch": "main"}

    def test_an_empty_value_does_not_overwrite_unknown(self, tmp_path):
        """`git rev-parse` failing leaves the printf writing an empty string,
        and a blank SHA reads as a bug rather than as an absent stamp."""
        path = self._write(tmp_path, "sha=\nbranch=develop\n")
        info = build.read_build_info(path)
        assert info["sha"] == "unknown"
        assert info["branch"] == "develop"

    def test_tolerates_a_partial_file(self, tmp_path):
        path = self._write(tmp_path, "branch=develop\n")
        info = build.read_build_info(path)
        assert info == {"sha": "unknown", "branch": "develop"}


class TestHealth:
    def test_still_reports_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_names_the_build(self, client, monkeypatch):
        monkeypatch.setattr(
            main.build, "BUILD_INFO", {"sha": "432b5af", "branch": "develop"}
        )
        assert client.get("/health").json()["build"] == {
            "sha": "432b5af",
            "branch": "develop",
        }

    def test_reports_an_unknown_build_rather_than_omitting_it(
        self, client, monkeypatch
    ):
        """The frontend compares against this. A missing key would read as a
        failed request; "unknown" says the stamp is absent."""
        monkeypatch.setattr(
            main.build, "BUILD_INFO", {"sha": "unknown", "branch": "unknown"}
        )
        body = client.get("/health").json()
        assert body["build"]["sha"] == "unknown"
