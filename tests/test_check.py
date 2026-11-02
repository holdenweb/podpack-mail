"""`flask mail check`: says what it would use, authenticates, and says how that went."""

from pathlib import Path

import pytest
from click.testing import Result
from flask import Flask

from conftest import LOGIN, PASSWORD, SiteFactory
from smtp_sink import Sink


def check(app: Flask) -> Result:
    return app.test_cli_runner().invoke(args=["mail", "check"])


@pytest.mark.usefixtures("trusted")
def test_a_working_credential_passes(smtp_site: Flask, sink: Sink) -> None:
    result = check(smtp_site)
    assert result.exit_code == 0, result.output
    assert "SMTP auth OK" in result.output
    assert LOGIN in result.output
    assert f"{len(PASSWORD)} characters" in result.output
    assert PASSWORD not in result.output
    assert sink.sessions[0].login == LOGIN


@pytest.mark.usefixtures("trusted")
def test_a_refused_credential_fails_and_says_so(
    site: SiteFactory, certificate: tuple[Path, Path]
) -> None:
    with Sink(*certificate, accept_auth=False) as refusing:
        app = site(config_overrides={"MAIL_BACKEND": "smtp", "MAIL_PORT": refusing.port})
        result = check(app)
    assert result.exit_code == 1
    assert "SMTP auth FAILED: SMTPAuthenticationError" in result.output
    assert PASSWORD not in result.output


def test_a_backend_that_sends_nothing_is_not_passed(site: SiteFactory) -> None:
    result = check(site())  # on a laptop, so the console backend
    assert result.exit_code == 1
    assert "nothing to check" in result.output
    assert "SMTP auth OK" not in result.output
