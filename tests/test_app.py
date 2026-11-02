"""Conformance with the podpack app contract, and where each setting comes from."""

import pytest

from conftest import ADDRESS, LOGIN, PASSWORD, SiteFactory

from podpack_mail import DEFAULT_PORT, DEFAULT_TIMEOUT, site_app


def test_the_app_names_itself_after_its_blueprint() -> None:
    assert site_app.name == site_app.blueprint.name == "mail"


def test_a_site_installs_it_by_naming_it(site: SiteFactory) -> None:
    app = site()
    assert app.extensions["podpack"].installed_from == {"mail": "podpack_mail"}
    assert "mailman" in app.extensions


def test_settings_come_from_the_config_file_and_the_environment(site: SiteFactory) -> None:
    app = site(
        host_config={
            "apps": {
                "mail": {
                    "server": "smtp.example.test",
                    "port": 2465,
                    "timeout": 7,
                    "sender_name": "Test Site",
                }
            }
        }
    )
    config = app.config
    assert (config["MAIL_SERVER"], config["MAIL_PORT"], config["MAIL_TIMEOUT"]) == (
        "smtp.example.test",
        2465,
        7,
    )
    assert (config["MAIL_USERNAME"], config["MAIL_PASSWORD"]) == (LOGIN, PASSWORD)
    assert config["MAIL_DEFAULT_SENDER"] == f"Test Site <{ADDRESS}>"
    assert (config["MAIL_USE_SSL"], config["MAIL_USE_TLS"]) == (True, False)


def test_what_the_file_leaves_out_takes_a_default(site: SiteFactory) -> None:
    app = site(host_config={"apps": {"mail": {"server": "smtp.example.test"}}})
    assert (app.config["MAIL_PORT"], app.config["MAIL_TIMEOUT"]) == (
        DEFAULT_PORT,
        DEFAULT_TIMEOUT,
    )
    # No display name, so the bare address.
    assert app.config["MAIL_DEFAULT_SENDER"] == ADDRESS


def test_what_the_caller_set_wins(site: SiteFactory) -> None:
    app = site(
        config_overrides={
            "MAIL_SERVER": "other.example.test",
            "MAIL_USERNAME": "other-login",
            "MAIL_DEFAULT_SENDER": "other@example.test",
        }
    )
    assert (
        app.config["MAIL_SERVER"],
        app.config["MAIL_USERNAME"],
        app.config["MAIL_DEFAULT_SENDER"],
    ) == ("other.example.test", "other-login", "other@example.test")


def test_flask_security_sends_from_the_deployment_address(site: SiteFactory) -> None:
    """Its sender defaults to a proxy that reads MAIL_DEFAULT_SENDER at send
    time, which is the only reason setting that one key is enough. Read back
    off a booted site, because that is where a setting is believed."""
    app = site()
    with app.app_context():
        assert str(app.config["SECURITY_EMAIL_SENDER"]) == f"Test Site <{ADDRESS}>"


def test_a_laptop_prints_rather_than_sends(site: SiteFactory) -> None:
    assert site().config["MAIL_BACKEND"] == "console"


def test_a_deployment_sends_by_smtp(site: SiteFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PODPACK_ENVIRONMENT", "production")
    assert site().config["MAIL_BACKEND"] == "smtp"


def test_an_explicit_backend_beats_the_derived_one(
    site: SiteFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PODPACK_ENVIRONMENT", "production")
    monkeypatch.setenv("MAIL_BACKEND", "dummy")
    assert site().config["MAIL_BACKEND"] == "dummy"


@pytest.mark.parametrize(
    ("unset", "complaint"),
    [
        ("MAIL_USERNAME", "MAIL_USERNAME is not set"),
        ("MAIL_ADDRESS", "MAIL_ADDRESS is not set"),
    ],
)
def test_smtp_will_not_start_without_its_settings(
    site: SiteFactory, monkeypatch: pytest.MonkeyPatch, unset: str, complaint: str
) -> None:
    monkeypatch.delenv(unset)
    with pytest.raises(RuntimeError, match=f"this site cannot start: .*{complaint}"):
        site(config_overrides={"MAIL_BACKEND": "smtp"})


def test_an_empty_value_counts_as_unset(site: SiteFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_ADDRESS", "  ")
    with pytest.raises(RuntimeError, match="MAIL_ADDRESS is not set"):
        site(config_overrides={"MAIL_BACKEND": "smtp"})


def test_smtp_will_not_start_without_a_server(site: SiteFactory) -> None:
    with pytest.raises(RuntimeError, match=r"\[apps.mail\] has no server"):
        site(host_config={"apps": {}}, config_overrides={"MAIL_BACKEND": "smtp"})


def test_starttls_is_refused(site: SiteFactory) -> None:
    with pytest.raises(RuntimeError, match="only implicit TLS"):
        site(config_overrides={"MAIL_BACKEND": "smtp", "MAIL_USE_TLS": True})


def test_a_backend_that_sends_nothing_needs_no_address(
    site: SiteFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MAIL_ADDRESS")
    monkeypatch.delenv("MAIL_USERNAME")
    assert site(config_overrides={"MAIL_BACKEND": "dummy"}).config["MAIL_BACKEND"] == "dummy"


def test_a_backend_nothing_can_import_stops_the_site(site: SiteFactory) -> None:
    with pytest.raises(ImportError):
        site(config_overrides={"MAIL_BACKEND": "no_such_backend"})


def test_without_the_password_the_site_will_not_start(
    site: SiteFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MAIL_PASSWORD")
    with pytest.raises(RuntimeError, match=r"MAIL_PASSWORD \(needed by app 'mail'\)"):
        site()


def test_status_reports_the_settings_and_never_the_password(site: SiteFactory) -> None:
    app = site(admin=lambda: True)
    response = app.test_client().get("/_status")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert LOGIN in body
    assert ADDRESS in body
    assert PASSWORD not in body
