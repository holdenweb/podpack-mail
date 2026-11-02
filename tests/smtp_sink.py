"""An SMTP server over implicit TLS, on 127.0.0.1, for the tests.

Adapted from the harness that exercised holdenweb.com's scratch/mailtest.py on
2026-11-01. It records who logged in, the envelope and the message, so that a
test can compare what the app was told with what reached the wire -- the only
place a mail configuration is ever really checked.
"""

import asyncio
import base64
import contextlib
import socket
import ssl
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    """One client connection, as the server saw it."""

    login: str | None = None
    password: str | None = None
    mail_from: str | None = None
    rcpt_to: list[str] = field(default_factory=list)
    data: str = ""


def make_certificate(directory: Path) -> tuple[Path, Path]:
    """A self-signed certificate for 127.0.0.1, which no trust store holds.

    That is the point of it: each test decides whether to trust it.
    """
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


class Sink:
    """Runs on its own event loop in a daemon thread, on a port the kernel picks.

    `accept_auth=False` answers every login with the 535 a real server gives a
    wrong password.
    """

    def __init__(self, cert: Path, key: Path, *, accept_auth: bool = True) -> None:
        self.accept_auth = accept_auth
        self.sessions: list[Session] = []
        self.port = 0
        self._context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self._context.load_cert_chain(cert, key)
        self._loop = asyncio.new_event_loop()
        # A client that rejects the certificate abandons the handshake, which
        # asyncio reports through the loop's exception handler. Here that is
        # the expected outcome of a test, not a fault to print.
        self._loop.set_exception_handler(lambda loop, context: None)
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "Sink":
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("the SMTP sink did not start")
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        server = self._loop.run_until_complete(
            asyncio.start_server(self._session, "127.0.0.1", 0, ssl=self._context)
        )
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()
        self._loop.run_forever()
        server.close()

    async def _session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        session = Session()
        self.sessions.append(session)

        def reply(line: str) -> None:
            writer.write((line + "\r\n").encode())

        reply("220 sink ESMTP")
        await writer.drain()
        while raw := await reader.readline():
            line = raw.decode().rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                reply("250-sink")
                reply("250 AUTH PLAIN")
            elif verb == "AUTH":
                _, session.login, session.password = (
                    base64.b64decode(line.split()[2]).decode().split("\0")
                )
                reply("235 2.7.0 ok" if self.accept_auth else "535 5.7.8 authentication failed")
            elif verb == "MAIL":
                session.mail_from = line.split(":", 1)[1].strip()
                reply("250 ok")
            elif verb == "RCPT":
                session.rcpt_to.append(line.split(":", 1)[1].strip())
                reply("250 ok")
            elif verb == "DATA":
                reply("354 go ahead")
                await writer.drain()
                while (body := (await reader.readline()).decode()) not in (".\r\n", ".\n", ""):
                    session.data += body
                reply("250 queued")
            elif verb == "QUIT":
                reply("221 bye")
                await writer.drain()
                break
            else:
                reply("250 ok")
            await writer.drain()
        writer.close()


@contextlib.contextmanager
def silent_server() -> Iterator[int]:
    """A port that takes a connection and then says nothing at all.

    The kernel completes the TCP handshake from the listen backlog without the
    socket ever being accepted, so a client gets as far as sending its TLS
    hello and then waits for an answer that never comes: a mail server that
    has stopped responding, as the site sees it.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        yield listener.getsockname()[1]
