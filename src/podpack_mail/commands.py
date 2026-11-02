"""The `mail` command group, carried by the app's blueprint.

Flask registers a blueprint's `cli` commands under the blueprint's own name, so
installing this app gives a site `flask --app <site> mail check` without the
site wiring anything. That is the blueprint's whole job: the app serves no
routes, and the blueprint exists to name it (podpack ADR-0003) and to carry
these.

A Flask command rather than a script, on podpack's distinction (ADR-0031):
checking the credential needs the running application -- its config, and the
transport this app configured.
"""

from typing import Any

import click
from flask import Blueprint, current_app
from flask_mailman.backends.smtp import EmailBackend as SMTPBackend

blueprint = Blueprint("mail", __name__)


def settings_report(config: Any) -> dict[str, Any]:
    """What an operator needs to see of the transport: everything but the password."""
    return {
        "backend": config.get("MAIL_BACKEND"),
        "server": f"{config.get('MAIL_SERVER')}:{config.get('MAIL_PORT')}",
        "username": config.get("MAIL_USERNAME"),
        "sender": config.get("MAIL_DEFAULT_SENDER"),
        "timeout": config.get("MAIL_TIMEOUT"),
    }


@blueprint.cli.command("check")
def check() -> None:
    """Authenticate against the mail server, and do nothing else.

    Written for holdenweb.com after an afternoon spent deciding whether a
    rejected credential was the password, the username, the wrong file or the
    site -- a question a password-reset round trip answers slowly, because a
    failure there could be any of them.

    Reports what the connection would use as well as the outcome, since a
    correct password presented as the wrong user fails identically to a wrong
    one. Exits non-zero on failure, so a deployment step can gate on it. The
    password's length is shown; its value never is.
    """
    config = current_app.config
    click.echo("mail configuration:")
    for name, value in settings_report(config).items():
        click.echo(f"  {name:<9} : {value}")
    password = config.get("MAIL_PASSWORD")
    described = f"{len(password)} characters" if password else "NOT SET"
    click.echo(f"  {'password':<9} : {described}")

    connection = current_app.extensions["mailman"].get_connection()
    if not isinstance(connection, SMTPBackend):
        # A console or dummy transport "authenticates" by doing nothing, and
        # reporting OK for it would be the worst possible answer here.
        backend = config.get("MAIL_BACKEND")
        click.echo(f"\nnothing to check: the {backend!r} backend sends no mail", err=True)
        raise SystemExit(1)
    try:
        connection.open()
    except Exception as exc:  # noqa: BLE001 -- smtplib, ssl and socket each raise their own
        click.echo(f"\nSMTP auth FAILED: {type(exc).__name__}", err=True)
        click.echo(f"  {exc}", err=True)
        raise SystemExit(1) from exc
    connection.close()
    click.echo("\nSMTP auth OK")
