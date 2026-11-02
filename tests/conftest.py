"""Fixtures that build a real podpack site with this app installed, and the
SMTP server it can be pointed at."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from podpack import create_app
from smtp_sink import Sink, make_certificate

SiteFactory = Callable[..., Flask]

PASSWORD = "test-mail-password"
LOGIN = "test-login"
ADDRESS = "test-stag@example.test"

HOST_CONFIG: dict[str, Any] = {
    "site": {"name": "test site", "environment": "test", "apps": ["podpack_mail"]},
    "apps": {"mail": {"server": "127.0.0.1", "sender_name": "Test Site"}},
}


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SiteFactory:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setenv("SECURITY_PASSWORD_SALT", "test-password-salt")
    monkeypatch.setenv("MAIL_PASSWORD", PASSWORD)
    monkeypatch.setenv("MAIL_USERNAME", LOGIN)
    monkeypatch.setenv("MAIL_ADDRESS", ADDRESS)
    # Whatever the shell running the suite happens to export must not decide a
    # result: each of these is read by the app, or by the TLS stack under it.
    for name in ("MAIL_BACKEND", "PODPACK_ENVIRONMENT", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.delenv(name, raising=False)

    def _build(**overrides: Any) -> Flask:
        config = {**HOST_CONFIG, **overrides.pop("host_config", {})}
        return create_app(
            host_config=config,
            data_root=tmp_path / "data",
            log_root=tmp_path / "logs",
            **overrides,
        )

    return _build


@pytest.fixture(scope="session")
def certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return make_certificate(tmp_path_factory.mktemp("tls"))


@pytest.fixture
def sink(certificate: tuple[Path, Path]) -> Iterator[Sink]:
    with Sink(*certificate) as running:
        yield running


@pytest.fixture
def trusted(
    site: SiteFactory, certificate: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make the sink's certificate the one thing this process trusts.

    OpenSSL reads SSL_CERT_FILE whenever a context loads its default locations,
    and `ssl.create_default_context()` -- which flask-mailman builds for every
    implicit-TLS connection -- does exactly that. Depends on `site` so that it
    runs after `site` has cleared the variable, not before.
    """
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate[0]))


@pytest.fixture
def smtp_site(site: SiteFactory, sink: Sink) -> Flask:
    """A site sending by SMTP, to the sink."""
    return site(config_overrides={"MAIL_BACKEND": "smtp", "MAIL_PORT": sink.port})
