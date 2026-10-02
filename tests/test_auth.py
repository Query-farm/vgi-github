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
