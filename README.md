# podpack-mail

A podpack app that gives a site its outbound mail. It is flask-mailman's SMTP
transport, configured from the site's config file and the deployment's
environment, so sending mail is a line in `[site] apps` rather than wiring in
the site's own `init`.

The distribution is `podpack-mail`, the import name (for a site's `apps` list)
is `podpack_mail`, and the app answers to `mail`. That name keys its config
section, `[apps.mail]`, and its command group, `flask mail …`.

## Installing it

```bash
uv add podpack-mail
```

```toml
[site]
apps = ["mysite", "podpack_mail"]

[apps.mail]
server = "smtp.example.com"
sender_name = "Example"
```

## Where each setting lives

| Setting | Where | Default |
| --- | --- | --- |
| `server` | `[apps.mail]` | none: SMTP will not start without it |
| `port` | `[apps.mail]` | `465` |
| `timeout` | `[apps.mail]` | `10` seconds |
| `sender_name` | `[apps.mail]` | none: the bare address |
| `MAIL_USERNAME` | the deployment's `.env` | none |
| `MAIL_ADDRESS` | the deployment's `.env` | none |
| `MAIL_PASSWORD` | the deployment's `secrets.env` | none: the site will not start without it |
| `MAIL_BACKEND` | the environment, if at all | `console` on a laptop, `smtp` anywhere else |

The file holds what is the same for every deployment of a site. The environment
holds what differs between them, and the secret (podpack ADR-0040). Anything
already in `app.config` when the app installs wins over both.

`MAIL_ADDRESS` becomes `MAIL_DEFAULT_SENDER`, with `sender_name` as its display
name. flask-security then sends from it without being told: its own sender
setting defaults to a proxy that reads `MAIL_DEFAULT_SENDER` at send time.

The timeout matters more than it looks. flask-mailman's own default is none at
all, and a send runs inside a request: without one, a server that stops
answering holds a gunicorn worker until gunicorn kills it, and the visitor gets
a 502 instead of the site's account of what went wrong.

## What it refuses

With the `smtp` backend, the site stops at boot if any of these is missing,
since each would otherwise surface on the first password reset:
- the server;
- `MAIL_USERNAME`;
- `MAIL_ADDRESS`.

It also stops if STARTTLS is asked for. Only implicit TLS is allowed, because
flask-mailman 1.1.1 verifies the server's certificate on that path and not on
STARTTLS.

## Checking a credential

```bash
podman compose exec web flask --app mysite mail check
```

This reports the server, the username, the sender and the password's length,
but never its value. It then authenticates, and exits non-zero on failure. A
backend that sends nothing fails the check rather than passing it.

## What a failure says is the site's business

flask-security catches nothing the transport raises, so by default a dead
credential turns "reset my password" into a 500. podpack passes
`PODPACK_MAIL_UTIL_CLS` to flask-security before any app installs, so the site
names its own failure policy there; this app ships none. holdenweb.com's
`ReportingMailUtil` is a worked example.

## On a laptop

`PODPACK_ENVIRONMENT` unset or `local` means the `console` backend: messages
are printed, not sent, because a laptop has no address of its own. To send for
real, set `MAIL_BACKEND=smtp` together with the settings above.

## Not yet

Receiving mail is planned to join this distribution. The `Message-ID` a send
mints and the fetch that matches replies to it will then live in one codebase.
Until then, `Message-ID`s are flask-mailman's, under the host's name.
