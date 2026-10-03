"""Optional token authentication: secret selection, validation, and the ATTACH mode."""

from __future__ import annotations

import pyarrow as pa
import pytest
from vgi.table_function import ResolvedSecrets

from vgi_github import auth


def _secret(token: str, *, type_: str = "github", scope: str = "") -> dict[str, pa.Scalar]:
    return {"token": pa.scalar(token), "type": pa.scalar(type_), "scope": pa.scalar(scope)}


class TestSecretSelection:
    def test_secret_is_found_by_type_whatever_its_name(self) -> None:
        """Resolved secrets are keyed by name; `CREATE SECRET gh (TYPE github…)` must still work.

        Looking the secret up by the type string only works when someone happens
        to name it `github`, which silently ran every query anonymously.
        """
        secrets = ResolvedSecrets({"my_token": _secret("ghp_named")})
        creds = auth.from_secrets(secrets, "https://api.github.com")
        assert creds is not None and creds.token == "ghp_named"

    def test_scope_picks_the_enterprise_secret(self) -> None:
        secrets = ResolvedSecrets(
            {
                "dotcom": _secret("ghp_public"),
                "ghe": _secret("ghe_token", scope="https://ghe.example.com"),
            }
        )
        assert auth.from_secrets(secrets, "https://ghe.example.com/api/v3").token == "ghe_token"
        assert auth.from_secrets(secrets, "https://api.github.com").token == "ghp_public"

    def test_other_secret_types_are_ignored(self) -> None:
        secrets = ResolvedSecrets({"s3": _secret("AKIA", type_="s3")})
        assert auth.from_secrets(secrets, "https://api.github.com") is None

    def test_plain_dict_keyed_by_type(self) -> None:
        assert auth.from_secrets({"github": {"token": "t"}}).token == "t"

    def test_no_secret_means_anonymous(self) -> None:
        assert auth.from_secrets(None) is None
        assert auth.from_secrets({}) is None

    def test_token_is_declared_redacted(self) -> None:
        field = auth.SECRET_SPEC.schema.field(auth.TOKEN)
        assert (field.metadata or {}).get(b"redact") == b"true"


class TestTokenValidation:
    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert auth.load("  ghp_x\n").token == "ghp_x"

    @pytest.mark.parametrize("token", ["", "   ", "ghp x"])
    def test_unusable_tokens_raise(self, token: str) -> None:
        with pytest.raises(auth.GitHubAuthError):
            auth.load(token)

    def test_token_never_appears_in_repr(self) -> None:
        assert "ghp_secret" not in repr(auth.load("ghp_secret"))

    def test_fingerprint_is_stable_and_not_the_token(self) -> None:
        a, b = auth.load("ghp_secret"), auth.load("ghp_secret")
        assert a.fingerprint == b.fingerprint and "ghp_secret" not in a.fingerprint
        assert a.fingerprint != auth.load("other").fingerprint


class TestModes:
    def test_auto_uses_a_secret_when_present(self, monkeypatch) -> None:
        monkeypatch.delenv(auth.ENV_TOKEN, raising=False)
        assert auth.for_call({"github": {"token": "t"}}, b"auto").token == "t"
        assert auth.for_call(None, b"auto") is None

    def test_required_without_a_secret_raises(self, monkeypatch) -> None:
        monkeypatch.delenv(auth.ENV_TOKEN, raising=False)
        with pytest.raises(auth.GitHubAuthError, match="required"):
            auth.for_call(None, b"required")

    def test_off_never_authenticates(self, monkeypatch) -> None:
        monkeypatch.setenv(auth.ENV_TOKEN, "env")
        assert auth.for_call({"github": {"token": "t"}}, b"off") is None

    def test_unknown_mode_reads_as_auto(self) -> None:
        assert auth.mode_of(b"bogus") == auth.AUTO
        assert auth.mode_of(None) == auth.AUTO


class TestEnvironmentFallback:
    def test_env_token_used_when_no_secret(self, monkeypatch) -> None:
        monkeypatch.setenv(auth.ENV_TOKEN, "from_env")
        assert auth.for_call(None, b"auto").token == "from_env"

    def test_secret_beats_env(self, monkeypatch) -> None:
        monkeypatch.setenv(auth.ENV_TOKEN, "from_env")
        assert auth.for_call({"github": {"token": "from_secret"}}, b"auto").token == "from_secret"

    def test_ambient_github_token_is_not_borrowed(self, monkeypatch) -> None:
        """A developer's shell token must not leak into a shared worker by accident."""
        monkeypatch.delenv(auth.ENV_TOKEN, raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "ambient")
        monkeypatch.setenv("GH_TOKEN", "ambient")
        assert auth.for_call(None, b"auto") is None


class TestAttach:
    def test_bad_mode_is_rejected_at_attach(self) -> None:
        from vgi_github.worker import GitHubCatalog

        with pytest.raises(ValueError, match="not one of"):
            GitHubCatalog().catalog_attach(name="github", options={"auth": "require"})


class TestTokenSource:
    """`token_source` names where to find a token — never the token itself."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        monkeypatch.delenv(auth.ENV_TOKEN, raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        monkeypatch.setattr(auth, "_local_sources_allowed", True)
        auth._gh_cache.clear()
        yield
        auth._gh_cache.clear()

    @staticmethod
    def _fake_gh(monkeypatch, *, token="gho_cli", returncode=0, stderr=""):
        calls: list[list[str]] = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            import subprocess

            return subprocess.CompletedProcess(cmd, returncode, stdout=token + "\n", stderr=stderr)

        monkeypatch.setattr(auth.shutil, "which", lambda name: "/usr/bin/gh")
        monkeypatch.setattr(auth.subprocess, "run", run)
        return calls

    def test_attach_bytes_round_trip(self) -> None:
        data = auth.encode_attach("required", "gh")
        assert auth.mode_of(data) == "required" and auth.token_source_of(data) == "gh"

    def test_legacy_attach_bytes_still_read(self) -> None:
        """Bytes from before token_source were the bare mode string."""
        assert auth.mode_of(b"required") == "required"
        assert auth.token_source_of(b"required") == ""

    def test_gh_login_is_used(self, monkeypatch) -> None:
        calls = self._fake_gh(monkeypatch)
        creds = auth.for_call(None, auth.encode_attach("auto", "gh"))
        assert creds is not None and creds.token == "gho_cli"
        assert calls[0][1:] == ["auth", "token", "--hostname", "github.com"]

    def test_gh_token_is_cached(self, monkeypatch) -> None:
        """A LATERAL makes many calls; gh must not be spawned for each."""
        calls = self._fake_gh(monkeypatch)
        for _ in range(5):
            auth.for_call(None, auth.encode_attach("auto", "gh"))
        assert len(calls) == 1

    def test_enterprise_host_is_asked_for(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3")
        calls = self._fake_gh(monkeypatch)
        auth.for_call(None, auth.encode_attach("auto", "gh"))
        assert calls[0][-1] == "ghe.example.com"

    def test_missing_gh_is_an_error_not_anonymous(self, monkeypatch) -> None:
        monkeypatch.setattr(auth.shutil, "which", lambda name: None)
        with pytest.raises(auth.GitHubAuthError, match="not on this machine"):
            auth.for_call(None, auth.encode_attach("auto", "gh"))

    def test_gh_not_logged_in_is_an_error(self, monkeypatch) -> None:
        self._fake_gh(monkeypatch, token="", returncode=1, stderr="no oauth token found for github.com")
        with pytest.raises(auth.GitHubAuthError, match="gh auth login"):
            auth.for_call(None, auth.encode_attach("auto", "gh"))

    def test_env_source_reads_the_standard_variables(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "from_github_token")
        assert auth.for_call(None, auth.encode_attach("auto", "env")).token == "from_github_token"
        monkeypatch.setenv("GH_TOKEN", "from_gh_token")
        assert auth.for_call(None, auth.encode_attach("auto", "env")).token == "from_gh_token"

    def test_env_source_without_a_variable_is_an_error(self) -> None:
        with pytest.raises(auth.GitHubAuthError, match="GH_TOKEN"):
            auth.for_call(None, auth.encode_attach("auto", "env"))

    def test_a_secret_beats_the_source(self, monkeypatch) -> None:
        calls = self._fake_gh(monkeypatch)
        creds = auth.for_call({"github": {"token": "from_secret"}}, auth.encode_attach("auto", "gh"))
        assert creds.token == "from_secret" and calls == []

    def test_the_source_satisfies_required(self, monkeypatch) -> None:
        self._fake_gh(monkeypatch)
        assert auth.for_call(None, auth.encode_attach("required", "gh")) is not None

    def test_off_ignores_the_source(self, monkeypatch) -> None:
        calls = self._fake_gh(monkeypatch)
        assert auth.for_call(None, auth.encode_attach("off", "gh")) is None and calls == []

    def test_a_shared_server_refuses_local_sources(self, monkeypatch) -> None:
        """On an HTTP worker, gh would run as the operator — anyone could borrow that login."""
        calls = self._fake_gh(monkeypatch)
        auth.disallow_local_sources()
        with pytest.raises(auth.GitHubAuthError, match="shared"):
            auth.for_call(None, auth.encode_attach("auto", "gh"))
        assert calls == []


class TestTokenSourceAttach:
    @pytest.fixture(autouse=True)
    def _allow(self, monkeypatch):
        monkeypatch.setattr(auth, "_local_sources_allowed", True)

    def test_bad_source_is_rejected_at_attach(self) -> None:
        from vgi_github.worker import GitHubCatalog

        with pytest.raises(ValueError, match="token_source"):
            GitHubCatalog().catalog_attach(name="github", options={"token_source": "keychain"})

    def test_shared_server_rejects_the_option_at_attach(self, monkeypatch) -> None:
        from vgi_github.worker import GitHubCatalog

        monkeypatch.setattr(auth, "_local_sources_allowed", False)
        with pytest.raises(ValueError, match="locally"):
            GitHubCatalog().catalog_attach(name="github", options={"token_source": "gh"})

    @pytest.mark.parametrize(
        ("argv", "allowed"),
        [
            ([], True),
            (["--http"], False),
            (["--port", "8000", "--http"], False),
            (["--unix=/tmp/s"], False),
            (["--tcp", "9000"], False),
            (["--describe"], True),
        ],
    )
    def test_server_flags_turn_local_sources_off(self, monkeypatch, argv, allowed) -> None:
        from vgi_github import worker

        monkeypatch.setattr(worker.GitHubWorker, "main", classmethod(lambda cls: None))
        monkeypatch.setattr(worker.sys, "argv", ["github_worker.py"])
        worker._start(argv)
        assert auth.local_sources_allowed() is allowed
