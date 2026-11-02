"""What reaches the wire -- the login, the envelope, the headers -- and what
happens when the server cannot be trusted, or does not answer."""

import ssl
import threading
import time

import pytest
from flask import Flask
from flask_mailman import EmailMessage

from conftest import ADDRESS, LOGIN, PASSWORD, SiteFactory
from smtp_sink import Sink, silent_server


def send(app: Flask) -> None:
    with app.app_context():
        EmailMessage("test subject", "test body", to=["test-to@example.test"]).send()


@pytest.mark.usefixtures("trusted")
def test_a_send_logs_in_and_leaves_from_the_deployment_address(
    smtp_site: Flask, sink: Sink
) -> None:
    send(smtp_site)
    [session] = sink.sessions
    assert (session.login, session.password) == (LOGIN, PASSWORD)
    assert session.mail_from == f"<{ADDRESS}>"
    assert session.rcpt_to == ["<test-to@example.test>"]
    assert f"From: Test Site <{ADDRESS}>" in session.data


def test_a_certificate_nobody_vouches_for_stops_the_send(smtp_site: Flask, sink: Sink) -> None:
    """Without `trusted`, the sink's self-signed certificate is in no trust store.

    This is the test that proves the server's certificate is checked at all:
    hand flask-mailman an unverified context and it goes red. The handshake
    fails before a session begins, so the password never leaves.
    """
    with pytest.raises(ssl.SSLCertVerificationError):
        send(smtp_site)
    assert sink.sessions == []


def test_a_server_that_never_answers_fails_inside_the_timeout(site: SiteFactory) -> None:
    outcome: list[BaseException] = []
    with silent_server() as port:
        app = site(
            host_config={"apps": {"mail": {"server": "127.0.0.1", "timeout": 1}}},
            config_overrides={"MAIL_BACKEND": "smtp", "MAIL_PORT": port},
        )

        def attempt() -> None:
            try:
                send(app)
            except BaseException as exc:  # noqa: BLE001 -- recorded, and asserted on below
                outcome.append(exc)

        # In a thread with a bounded join, so that a timeout which never fires
        # fails this test rather than hanging the suite.
        started = time.monotonic()
        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), "the send was still waiting after ten seconds"
    elapsed = time.monotonic() - started
    assert len(outcome) == 1
    assert isinstance(outcome[0], TimeoutError), repr(outcome[0])
    assert elapsed < 5
