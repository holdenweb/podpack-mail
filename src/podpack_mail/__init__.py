"""The mail app: a site's outbound mail, installed like any other feature.

It configures flask-mailman's transport from the site's `[apps.mail]` section
and the deployment's environment, so that a site sends mail by listing this
app rather than by wiring an extension in its own `init` (podpack ADR-0041,
which supersedes ADR-0025's mail clause). What a *failure* says stays the
site's: podpack hands `PODPACK_MAIL_UTIL_CLS` to flask-security before any app
is installed, so the site names that class itself, and this app ships none.

Where each setting lives, and why there:

- `[apps.mail]` -- `server`, `port`, `timeout`, `sender_name`. Committed with
  the site, and the same for every deployment of it.
- the environment -- `MAIL_USERNAME` and `MAIL_ADDRESS` from `.env`,
  `MAIL_PASSWORD` from `secrets.env`: what differs between a site's
  deployments, or must stay out of git (podpack ADR-0040).

Anything a caller has already put in `app.config` wins over both, which is how
a test swaps the transport for `dummy`.
"""

import os
from email.utils import formataddr
from typing import Any

from flask import Flask, current_app
from flask_mailman import Mail
from flask_mailman.backends.smtp import EmailBackend as SMTPBackend

from podpack import Backup, SiteApp, app_config
from podpack.proxy import LOCAL, deployment_environment

from .commands import blueprint, settings_report

DEFAULT_PORT = 465
"""Implicit TLS: the only way this app will speak SMTP (see `_refuse_to_start`)."""

DEFAULT_TIMEOUT = 10
"""Seconds. flask-mailman's own default is no timeout at all, and a send runs
inside a request on one of a site's few gunicorn workers. A server that stopped
answering would hold the worker until gunicorn killed it at thirty seconds, and
the visitor would get the proxy's 502 rather than the site's own account of the
failure."""

mail = Mail()
"""Unbound, and attached in `_init`, so that several sites can be built in one
interpreter -- as every test suite builds them."""


class MailApp(SiteApp):
    """Reports its settings to `/_status`, and deliberately reports no health.

    The only real test of a mail transport is to log in to it, and `/healthz`
    runs every ten seconds: doing that six times a minute would be an abuse of
    somebody else's server. A credential that has stopped working is what
    `flask mail check` is for.
    """

    def status(self) -> dict[str, Any]:
        return settings_report(current_app.config)


def _init(app: Flask) -> None:
    """Settle the transport before the first request, or refuse to start."""
    with app.app_context():
        settings = app_config("mail")
    _default(app, "MAIL_BACKEND", _env("MAIL_BACKEND") or _derived_backend())
    _default(app, "MAIL_SERVER", settings.get("server"))
    _default(app, "MAIL_PORT", settings.get("port", DEFAULT_PORT))
    _default(app, "MAIL_TIMEOUT", settings.get("timeout", DEFAULT_TIMEOUT))
    _default(app, "MAIL_USE_SSL", True)
    _default(app, "MAIL_USE_TLS", False)
    _default(app, "MAIL_USERNAME", _env("MAIL_USERNAME"))
    _default(app, "MAIL_PASSWORD", _env("MAIL_PASSWORD"))
    # flask-security's SECURITY_EMAIL_SENDER is already set by now -- podpack
    # installs login before any app -- but its default is a proxy that reads
    # MAIL_DEFAULT_SENDER at send time, so this is all it takes for a password
    # reset to leave from the deployment's own address.
    address = _env("MAIL_ADDRESS")
    if address:
        sender = formataddr((settings.get("sender_name", ""), address))
        _default(app, "MAIL_DEFAULT_SENDER", sender)
    _refuse_to_start(app.config)
    mail.init_app(app)


def _default(app: Flask, key: str, value: Any) -> None:
    """`setdefault`, except that nothing is never a value.

    flask-security reads the sender as `config.get("MAIL_DEFAULT_SENDER",
    "no-reply@localhost")`, so a key that is present and None is not absent:
    the mail goes out from `None`. Leaving the key out keeps flask-mailman's
    and flask-security's own fallbacks honest, and `_refuse_to_start` keeps
    them from mattering where they would.
    """
    if value is not None:
        app.config.setdefault(key, value)


def _env(name: str) -> str | None:
    """A variable from the environment, an empty value counting as unset -- as
    podpack's own secrets check counts it, because `MAIL_ADDRESS=` in a file is
    not an address."""
    return os.environ.get(name, "").strip() or None


def _derived_backend() -> str:
    """`console` on a laptop, `smtp` anywhere else.

    Derived from `PODPACK_ENVIRONMENT` as podpack derives the proxy hop count
    (ADR-0039): a value worked out from what the deployment already says
    cannot be forgotten. A laptop has no address of its own (ADR-0040), so the
    safe way for it to fail is to print a message rather than send it.
    """
    return "console" if deployment_environment() == LOCAL else "smtp"


def _refuse_to_start(config: Any) -> None:
    """Stop the site at boot when SMTP is chosen but cannot work, or would work
    unsafely.

    Each gap otherwise surfaces on the first password reset: no server is a
    connection to flask-mailman's `localhost:25`, no username an
    unauthenticated send the provider refuses, and no address mail from
    `no-reply@localhost`. Worded like podpack's own secrets check, so a
    deployment that stops says why in the voice its operator already knows.

    STARTTLS is refused rather than supported: flask-mailman 1.1.1 upgrades the
    connection with `context=None`, which verifies no certificate, while its
    implicit-TLS path builds `ssl.create_default_context()` and does.

    The backend is resolved the way flask-mailman resolves it, so `smtp`, its
    dotted path and a subclass all count -- and a name nothing can import fails
    here, at boot, rather than on the first send.
    """
    if not issubclass(mail.import_backend(config["MAIL_BACKEND"]), SMTPBackend):
        return
    problems = [
        message
        for wrong, message in (
            (not config.get("MAIL_SERVER"), "[apps.mail] has no server"),
            (not config.get("MAIL_USERNAME"), "MAIL_USERNAME is not set"),
            (not config.get("MAIL_DEFAULT_SENDER"), "MAIL_ADDRESS is not set"),
            (
                config.get("MAIL_USE_TLS") or not config.get("MAIL_USE_SSL"),
                "only implicit TLS is allowed (MAIL_USE_SSL), because STARTTLS "
                "here would not verify the server's certificate",
            ),
        )
        if wrong
    ]
    if problems:
        raise RuntimeError(
            "this site cannot start: mail is to go by SMTP, but "
            + "; ".join(problems)
            + ". The server comes from [apps.mail] in the site's config file, "
            "and MAIL_USERNAME and MAIL_ADDRESS from the deployment's .env."
        )


site_app = MailApp(
    blueprint=blueprint,
    init=_init,
    needs_secrets=frozenset({"MAIL_PASSWORD"}),
    # Nothing is ever written to the data directory podpack makes for every
    # app. Saying so means a backup reports it as stateless rather than as
    # something nobody vouched for (ADR-0035).
    backs_up=Backup(data=False),
)
