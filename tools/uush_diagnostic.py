"""Bounded, operator-run Linux diagnostic. Default invocation is entirely offline."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import multiprocessing as mp
import os
import platform
import re
import selectors
import signal
import socket
import ssl
import sys
import time
from pathlib import Path
from xml.parsers import expat

HOST = "www.youtube.com"
CHANNEL = "UC0o-_FwPhZS5Xr0XTmwqwkw"
TARGET = "/feeds/videos.xml?playlist_id=UUSH0o-_FwPhZS5Xr0XTmwqwkw"
ENDPOINT = "https://" + HOST + TARGET
CAPTURE_LIMIT = 256 * 1024
OUTPUT_LIMIT = 64 * 1024
STAGES = ("DNS", "TCP", "TLS", "HTTP", "XML")
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"


class DiagnosticError(Exception):
    """Only fixed, public error codes may cross the worker boundary."""


class RecordError(DiagnosticError):
    """XML is structurally valid, but its records cannot qualify extraction."""


def utc():
    return dt.datetime.now(dt.UTC).isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


class Receiver:
    """No read-ahead: charge every decrypted HTTP byte before requesting more."""

    def __init__(self, stream, sent_at, clock=time.monotonic):
        self.stream, self.clock, self.sent_at = stream, clock, sent_at
        self.total = 0
        self.first_byte = None

    def read(self, amount):
        if self.total >= CAPTURE_LIMIT:
            raise DiagnosticError("response_limit")
        data = self.stream.recv(min(amount, CAPTURE_LIMIT - self.total))
        if data and self.first_byte is None:
            self.first_byte = self.clock() - self.sent_at
        self.total += len(data)
        return data

    def exact(self, amount):
        data = bytearray()
        while len(data) < amount:
            part = self.read(amount - len(data))
            if not part:
                raise DiagnosticError("truncated_http")
            data.extend(part)
        return bytes(data)

    def line(self):
        data = bytearray()
        while not data.endswith(b"\r\n"):
            part = self.read(1)
            if not part:
                raise DiagnosticError("truncated_http")
            data.extend(part)
        return bytes(data[:-2])


def receive_http(reader, evidence, notify):
    status = reader.line()
    match = re.fullmatch(rb"HTTP/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e]*)?", status)
    if not match:
        raise DiagnosticError("invalid_http_status")
    headers = {}
    while True:
        line = reader.line()
        if not line:
            break
        name, sep, value = line.partition(b":")
        if not sep or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise DiagnosticError("invalid_http_header")
        key = name.lower()
        if key in headers:
            raise DiagnosticError("duplicate_http_header")
        if any(c < 32 and c != 9 for c in value) or b"\x7f" in value:
            raise DiagnosticError("invalid_http_header")
        headers[key] = value.strip()
    code = int(match[1])
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0].lower()
    evidence.update(
        http_status=code,
        content_type=(
            content_type.decode("ascii")
            if content_type
            in (b"application/atom+xml", b"application/xml", b"text/xml", b"text/html")
            else "other"
            if content_type
            else None
        ),
        redirect_destination_present=b"location" in headers if 300 <= code < 400 else False,
        redirect_count=0,
        tls_validation="SUCCESS",
        connectivity="PASS",
        time_to_first_byte_seconds=reader.first_byte,
        header_bytes=reader.total,
    )
    notify({"evidence": evidence.copy()})
    if 300 <= code < 400:
        raise DiagnosticError("redirect_not_followed")
    if headers.get(b"content-encoding", b"identity").lower() != b"identity":
        raise DiagnosticError("unexpected_compression")
    if code != 200:
        raise DiagnosticError("http_status_not_200")
    if content_type not in (b"application/atom+xml", b"application/xml", b"text/xml"):
        raise DiagnosticError("unexpected_content_type")
    transfer = headers.get(b"transfer-encoding")
    length = headers.get(b"content-length")
    if transfer and length:
        raise DiagnosticError("ambiguous_http_framing")
    body = bytearray()
    if transfer:
        if transfer.lower() != b"chunked":
            raise DiagnosticError("unsupported_transfer_encoding")
        while True:
            size_line = reader.line()
            if not re.fullmatch(rb"[0-9A-Fa-f]{1,8}", size_line):
                raise DiagnosticError("invalid_chunk")
            size = int(size_line, 16)
            if size == 0:
                if reader.line():
                    raise DiagnosticError("unsupported_trailers")
                break
            if size > CAPTURE_LIMIT - reader.total:
                raise DiagnosticError("response_limit")
            body.extend(reader.exact(size))
            if reader.exact(2) != b"\r\n":
                raise DiagnosticError("invalid_chunk")
    elif length is not None:
        if not re.fullmatch(rb"[0-9]{1,10}", length):
            raise DiagnosticError("invalid_content_length")
        size = int(length)
        if size > CAPTURE_LIMIT - reader.total:
            raise DiagnosticError("response_limit")
        body.extend(reader.exact(size))
    else:
        while True:
            part = reader.read(4096)
            if not part:
                break
            body.extend(part)
    return bytes(body)


def parse_atom(body):
    """Validate the whole document structurally; collect at most ten entries."""
    parser = expat.ParserCreate(namespace_separator="|")
    stack, records = [], []
    entry = None
    entry_count = 0
    fields = {}
    record_error = None

    def unsafe(*_):
        raise DiagnosticError("unsafe_xml")

    def start(name, attrs):
        nonlocal entry, entry_count, fields
        stack.append(name)
        if len(stack) > 32:
            raise DiagnosticError("xml_depth_limit")
        if len(stack) == 1 and name != ATOM + "|feed":
            raise DiagnosticError("not_atom_feed")
        if name == ATOM + "|entry":
            if len(stack) != 2:
                raise DiagnosticError("invalid_atom_entry")
            entry_count += 1
            entry = {} if entry_count <= 10 else None
            fields = {}
        if entry is not None and len(stack) == 3:
            if name in fields:
                raise DiagnosticError("duplicate_atom_field")
            fields[name] = ""
            if name == ATOM + "|link" and attrs.get("rel", "alternate") == "alternate":
                entry["returned_link"] = attrs.get("href")

    def chars(text):
        if entry is not None and len(stack) == 3:
            name = stack[-1]
            # Store only the fields required for attribution and metadata.
            if name in (
                YT + "|channelId",
                YT + "|videoId",
                ATOM + "|title",
                ATOM + "|published",
                ATOM + "|updated",
            ):
                fields[name] = (fields[name] + text)[:513]

    def end(name):
        nonlocal entry, record_error
        if name == ATOM + "|entry" and entry is not None:
            channel = fields.get(YT + "|channelId", "").strip()
            video = fields.get(YT + "|videoId", "").strip()
            if channel != CHANNEL or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
                record_error = "record_attribution_failed"
                entry = None
                stack.pop()
                return
            title = fields.get(ATOM + "|title")
            record = {
                "channel_id": channel,
                "video_id": video,
                "canonical_url": "https://www.youtube.com/watch?v=" + video,
                "title": title[:512] if title is not None else None,
                "title_truncated": title is not None and len(title) > 512,
                "duration_seconds": None,
                "classification": "unknown",
                "membership_evidence": None,
                "provenance": ENDPOINT,
            }
            link = entry.get("returned_link")
            record["returned_link"] = (
                link
                if link
                in (
                    "https://www.youtube.com/watch?v=" + video,
                    "https://www.youtube.com/shorts/" + video,
                )
                else None
            )
            for tag in ("published", "updated"):
                value = fields.get(ATOM + "|" + tag)
                if value is not None:
                    try:
                        parsed = dt.datetime.fromisoformat(value)
                        if parsed.tzinfo is None:
                            raise ValueError
                    except ValueError:
                        record_error = "invalid_publication_timestamp"
                record[tag + "_at"] = value
            record["observed_at"] = utc()
            records.append(record)
            entry = None
        stack.pop()

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = chars
    parser.StartDoctypeDeclHandler = unsafe
    parser.EntityDeclHandler = unsafe
    parser.ExternalEntityRefHandler = unsafe
    for offset in range(0, len(body), 4096):
        parser.Parse(body[offset : offset + 4096], False)
    parser.Parse(b"", True)
    if record_error:
        raise RecordError(record_error)
    return records


class LiveTransport:
    resolve = staticmethod(socket.getaddrinfo)
    make_socket = staticmethod(socket.socket)

    @staticmethod
    def wrap(sock):
        return ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)


def empty_evidence():
    return {
        "http_status": None,
        "content_type": None,
        "tls_validation": None,
        "selected_family": None,
        "returned_families": [],
        "time_to_first_byte_seconds": None,
        "response_bytes": 0,
        "xml_valid": None,
        "records": [],
        "connectivity": "UNQUALIFIED",
        "extraction": "UNQUALIFIED",
        "dns_operations": 0,
        "tcp_attempts": 0,
        "http_requests": 0,
        "redirect_count": 0,
    }


def run_request(transport, emit, deadline, clock=time.monotonic, xml_parser=parse_atom):
    evidence = empty_evidence()
    active = None
    stage_start = None
    sock = None
    reader = None

    def begin(stage):
        nonlocal active, stage_start
        active, stage_start = stage, clock()
        emit({"stage": stage, "event": "begin"})
        if clock() >= deadline:
            raise TimeoutError

    def finish(outcome="SUCCESS", error=None):
        emit(
            {
                "stage": active,
                "event": "end",
                "outcome": outcome,
                "elapsed_seconds": round(clock() - stage_start, 6),
                "error": error,
            }
        )

    try:
        begin("DNS")
        evidence["dns_operations"] = 1
        emit({"evidence": evidence.copy()})
        addresses = transport.resolve(HOST, 443, type=socket.SOCK_STREAM)
        addresses = [a for a in addresses if a[0] in (socket.AF_INET, socket.AF_INET6)]
        if not addresses:
            raise DiagnosticError("no_usable_address")
        selected = next((a for a in addresses if a[0] == socket.AF_INET), addresses[0])
        evidence["returned_families"] = sorted(
            {"IPv4" if a[0] == socket.AF_INET else "IPv6" for a in addresses}
        )
        evidence["selected_family"] = "IPv4" if selected[0] == socket.AF_INET else "IPv6"
        finish()
        begin("TCP")
        evidence["tcp_attempts"] = 1
        emit({"evidence": evidence.copy()})
        sock = transport.make_socket(selected[0], socket.SOCK_STREAM)
        sock.settimeout(max(0.001, deadline - clock()))
        sock.connect(selected[4])
        finish()
        begin("TLS")
        sock.settimeout(max(0.001, deadline - clock()))
        sock = transport.wrap(sock)
        evidence["tls_validation"] = "SUCCESS"
        version = sock.version()
        evidence["tls_version"] = version if version in ("TLSv1.2", "TLSv1.3") else "other"
        finish()
        begin("HTTP")
        evidence["http_requests"] = 1
        emit({"evidence": evidence.copy()})
        sock.settimeout(max(0.001, deadline - clock()))
        sock.sendall(
            (
                f"GET {TARGET} HTTP/1.1\r\nHost: {HOST}\r\n"
                "User-Agent: CatsChannel-Metadata-Diagnostic/1.0\r\n"
                "Accept: application/atom+xml\r\nAccept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        reader = Receiver(sock, clock(), clock)
        body = receive_http(reader, evidence, emit)
        evidence["response_bytes"] = reader.total
        evidence["time_to_first_byte_seconds"] = reader.first_byte
        emit({"evidence": evidence.copy()})
        finish()
        begin("XML")
        evidence["records"] = xml_parser(body)
        evidence["xml_valid"] = True
        evidence["extraction"] = "PASS" if evidence["records"] else "UNQUALIFIED"
        finish()
    except Exception as exc:  # noqa: BLE001 -- never disclose raw transport/parser exceptions
        if isinstance(exc, (TimeoutError, socket.timeout)):
            outcome, code = "TIMEOUT", "worker_deadline"
        elif isinstance(exc, ssl.SSLCertVerificationError):
            outcome, code = "FAILED", "tls_verification_failed"
            evidence["tls_validation"] = "FAILED"
        elif isinstance(exc, DiagnosticError):
            outcome, code = "FAILED", str(exc)
        else:
            outcome, code = "FAILED", "stage_operation_failed"
        if active == "XML" and outcome == "FAILED":
            evidence["xml_valid"] = isinstance(exc, RecordError)
        finish(outcome, code)
    finally:
        if reader:
            evidence["response_bytes"] = reader.total
            evidence["time_to_first_byte_seconds"] = reader.first_byte
        if sock:
            sock.close()
        emit({"evidence": evidence, "done": True})


def worker(channel, deadline, scenario):
    # The isolated worker emits only bounded protocol events, never raw exceptions.
    with open(os.devnull, "wb") as null:
        os.dup2(null.fileno(), 2)
    used = 0

    def emit(event):
        nonlocal used
        data = encoded(event)
        used += len(data)
        if used > OUTPUT_LIMIT:
            raise DiagnosticError("ipc_limit")
        channel.sendall(data)

    def expired(*_):
        raise TimeoutError

    if hasattr(signal, "setitimer"):
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic()))
    try:
        if scenario == "live":
            run_request(LiveTransport(), emit, deadline)
        else:
            # Explicitly offline transport; scenario names cannot select endpoints.
            run_request(
                FakeTransport(scenario),
                emit,
                deadline,
                xml_parser=stalled_xml if scenario == "blocking_xml" else parse_atom,
            )
    finally:
        channel.close()


def supervise(scenario="live", timings=(25.0, 26.0, 27.0, 29.0)):
    started, started_utc = time.monotonic(), utc()
    result = {
        "started_at": started_utc,
        "endpoint": ENDPOINT,
        "stages": {s: {"outcome": "NOT_ATTEMPTED", "elapsed_seconds": None} for s in STAGES},
        "evidence": empty_evidence(),
        "worker_reaped": False,
        "termination_sent": False,
        "kill_sent": False,
        "production_qualification": "BLOCKED",
        "shorts_membership": "UNQUALIFIED",
    }
    parent, child = socket.socketpair()
    parent.setblocking(False)
    process = mp.get_context("spawn").Process(
        target=worker, args=(child, started + timings[0], scenario)
    )
    active, active_start = None, None
    buffer, total = bytearray(), 0
    done = False
    selector = selectors.DefaultSelector()
    selector.register(parent, selectors.EVENT_READ)
    try:
        process.start()
        child.close()
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= timings[1] and process.is_alive() and not result["termination_sent"]:
                process.terminate()
                result["termination_sent"] = True
            if elapsed >= timings[2] and process.is_alive() and not result["kill_sent"]:
                process.kill()
                result["kill_sent"] = True
            if elapsed >= timings[3]:
                break
            events = selector.select(min(0.02, max(0, timings[3] - elapsed)))
            eof = False
            if events:
                try:
                    data = parent.recv(4096)
                except ConnectionResetError:
                    data = b""
                eof = not data
                total += len(data)
                if total > OUTPUT_LIMIT:
                    result["supervisor_error"] = "ipc_limit"
                    break
                buffer.extend(data)
                while b"\n" in buffer:
                    raw, _, tail = buffer.partition(b"\n")
                    buffer = bytearray(tail)
                    event = json.loads(raw)
                    if "stage" in event:
                        stage = event["stage"]
                        if event["event"] == "begin":
                            active, active_start = stage, time.monotonic()
                        else:
                            result["stages"][stage] = {
                                k: event[k] for k in ("outcome", "elapsed_seconds", "error")
                            }
                            active = None
                    if "evidence" in event:
                        result["evidence"] = event["evidence"]
                    done = done or event.get("done", False)
            if eof:
                break
        if not done and active:
            result["stages"][active] = {
                "outcome": "TIMEOUT" if result["termination_sent"] else "FAILED",
                "elapsed_seconds": round(time.monotonic() - active_start, 6),
                "error": "supervisor_deadline" if result["termination_sent"] else "worker_stopped",
            }
            if active == "HTTP":
                # A killed worker may have read bytes since its last event.
                evidence = result["evidence"]
                evidence["response_bytes_confirmed_min"] = evidence.get("header_bytes", 0)
                evidence["response_bytes"] = None
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.kill()
                result["kill_sent"] = True
            process.join(timeout=max(0, started + timings[3] + 0.5 - time.monotonic()))
            result["worker_reaped"] = not process.is_alive()
            if result["worker_reaped"]:
                process.close()
        selector.close()
        parent.close()
        child.close()
    result.update(
        ended_at=utc(),
        elapsed_seconds=round(time.monotonic() - started, 6),
        tooling={"python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION},
        network_policy="direct socket; environment proxies ignored; egress not independently verified",
    )
    if sys.platform.startswith("linux"):
        try:
            release = platform.freedesktop_os_release()
            result["tooling"]["distribution"] = {
                key: release.get(key)
                if re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", release.get(key, ""))
                else None
                for key in ("ID", "VERSION_ID")
            }
        except OSError:
            result["tooling"]["distribution"] = None
    if not result["worker_reaped"]:
        result["supervisor_error"] = "worker_not_reaped"
    return result


# Offline test doubles are deliberately contained here so the copied script needs
# no project imports, test runner, third-party dependencies or network access.
def stall():
    if hasattr(signal, "SIGTERM") and sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)
    while True:
        time.sleep(0.01)


def stalled_xml(body):
    stall()


def fixture_atom(count=1, channel=CHANNEL):
    entry = (
        f"<entry><yt:channelId>{channel}</yt:channelId>"
        "<yt:videoId>abcdefghijk</yt:videoId><title>Cat</title>"
        "<published>2026-11-06T00:00:00Z</published></entry>"
    )
    return (f'<feed xmlns="{ATOM}" xmlns:yt="{YT}">' + entry * count + "</feed>").encode()


def fixture_response(body, headers=b"", status=b"200 OK"):
    return (
        b"HTTP/1.1 " + status + b"\r\nContent-Type: application/atom+xml\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n" + headers + b"\r\n" + body
    )


class FakeTransport:
    def __init__(self, scenario):
        self.scenario, self.calls, self.sent = scenario, [], b""
        body = fixture_atom(
            12 if scenario == "many" else 1, "wrong" if scenario == "mismatch" else CHANNEL
        )
        if scenario == "unsafe":
            body = b'<!DOCTYPE feed [<!ENTITY cat "cat">]>' + body
        if scenario == "malformed":
            body = b"<feed>"
        self.data = io.BytesIO(fixture_response(body))
        if scenario == "redirect":
            self.data = io.BytesIO(
                fixture_response(b"", b"Location: https://private.invalid/\r\n", b"302 Found")
            )
        elif scenario == "compression":
            self.data = io.BytesIO(fixture_response(body, b"Content-Encoding: gzip\r\n"))
        elif scenario == "headers":
            self.data = io.BytesIO(b"HTTP/1.1 200 OK\r\nX-Fill: " + b"x" * CAPTURE_LIMIT)
        elif scenario == "body":
            self.data = io.BytesIO(fixture_response(b"x" * CAPTURE_LIMIT))

    def resolve(self, *args, **kwargs):
        self.calls.append("DNS")
        if self.scenario == "blocking_dns":
            stall()
        return [
            (socket.AF_INET6, 1, 6, "", ("::1", 443, 0, 0)),
            (socket.AF_INET, 1, 6, "", ("127.0.0.1", 443)),
        ]

    def make_socket(self, *args):
        self.calls.append("SOCKET")
        return self

    def settimeout(self, value):
        pass

    def connect(self, address):
        self.calls.append("TCP")
        if self.scenario == "blocking_tcp":
            stall()
        if self.scenario == "connection":
            raise OSError("PRIVATE_VALUE_MUST_NOT_LEAK")

    def wrap(self, sock):
        self.calls.append("TLS")
        if self.scenario == "blocking_tls":
            stall()
        if self.scenario == "certificate":
            raise ssl.SSLCertVerificationError("PRIVATE_CERTIFICATE_MUST_NOT_LEAK")
        return sock

    def version(self):
        return "TLSv1.3"

    def sendall(self, data):
        self.calls.append("HTTP")
        self.sent += data

    def recv(self, amount):
        if self.scenario == "blocking_http":
            stall()
        if self.scenario == "slow_http":
            raise TimeoutError("PRIVATE_ADDRESS_MUST_NOT_LEAK")
        return self.data.read(amount)

    def close(self):
        pass


def self_check():
    import unittest

    class Checks(unittest.TestCase):
        def test_xml_validation(self):
            records = parse_atom(fixture_atom())
            self.assertEqual(records[0]["published_at"], "2026-11-06T00:00:00Z")
            self.assertIsNone(records[0]["duration_seconds"])
            self.assertIsNone(records[0]["membership_evidence"])
            self.assertEqual(parse_atom(fixture_atom(0)), [])
            self.assertEqual(len(parse_atom(fixture_atom(20))), 10)
            for text in (
                fixture_atom().replace(b"Cat", b"x" * 600),
                fixture_atom().replace(b"<title>Cat</title>", b""),
            ):
                record = parse_atom(text)[0]
                self.assertTrue(record["title_truncated"] or record["title"] is None)
            with self.assertRaises(DiagnosticError):
                parse_atom(fixture_atom().replace(b"2026-11-06T00:00:00Z", b"not-a-date"))
            with self.assertRaises(DiagnosticError):
                parse_atom(
                    (
                        f'<!DOCTYPE feed SYSTEM "https://private.invalid/"><feed xmlns="{ATOM}"/>'
                    ).encode("utf-16")
                )

        def test_framing_and_byte_accounting(self):
            body = fixture_atom()
            wire = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/xml\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
                + f"{len(body):x}".encode()
                + b"\r\n"
                + body
                + b"\r\n0\r\n\r\n"
            )
            transport = FakeTransport("valid")
            transport.data = io.BytesIO(wire)
            reader = Receiver(transport, 1.0, clock=lambda: 2.0)
            evidence = {}
            self.assertEqual(receive_http(reader, evidence, lambda _: None), body)
            self.assertEqual(reader.total, len(wire))
            self.assertEqual(reader.first_byte, 1.0)

        def test_responses(self):
            expected = {
                "valid": ("XML", "SUCCESS"),
                "many": ("XML", "SUCCESS"),
                "mismatch": ("XML", "FAILED"),
                "unsafe": ("XML", "FAILED"),
                "malformed": ("XML", "FAILED"),
                "connection": ("TCP", "FAILED"),
                "certificate": ("TLS", "FAILED"),
                "slow_http": ("HTTP", "TIMEOUT"),
                "redirect": ("HTTP", "FAILED"),
                "compression": ("HTTP", "FAILED"),
                "headers": ("HTTP", "FAILED"),
                "body": ("HTTP", "FAILED"),
            }
            for scenario, (stage, outcome) in expected.items():
                with self.subTest(scenario=scenario):
                    transport, events = FakeTransport(scenario), []
                    run_request(transport, events.append, 100.0, clock=lambda: 1.0)
                    ends = [e for e in events if e.get("event") == "end"]
                    self.assertEqual((ends[-1]["stage"], ends[-1]["outcome"]), (stage, outcome))
                    evidence = events[-1]["evidence"]
                    self.assertLessEqual(evidence["response_bytes"], CAPTURE_LIMIT)
                    self.assertLessEqual(len(evidence["records"]), 10)
                    self.assertLessEqual(sum(len(encoded(e)) for e in events), OUTPUT_LIMIT)
                    self.assertNotIn("PRIVATE", str(events))
                    self.assertNotIn("127.0.0.1", str(events))
                    self.assertEqual(transport.calls.count("DNS"), 1)
                    self.assertLessEqual(transport.calls.count("TCP"), 1)
                    self.assertLessEqual(transport.calls.count("HTTP"), 1)
                    self.assertEqual(evidence["selected_family"], "IPv4")
                    if scenario in ("valid", "many"):
                        self.assertEqual(evidence["extraction"], "PASS")
                        self.assertEqual(len(evidence["records"]), 10 if scenario == "many" else 1)
                    if scenario == "redirect":
                        self.assertEqual(evidence["connectivity"], "PASS")
                        self.assertTrue(evidence["redirect_destination_present"])
                    self.assertNotIn(b"Cookie:", transport.sent)
                    self.assertNotIn(b"Authorization:", transport.sent)

        def test_worker_success(self):
            result = supervise("valid")
            self.assertTrue(result["worker_reaped"])
            self.assertEqual(result["evidence"]["extraction"], "PASS")
            self.assertTrue(all(s["outcome"] == "SUCCESS" for s in result["stages"].values()))
            self.assertLessEqual(len(encoded(result)), OUTPUT_LIMIT)

        def test_stalled_worker(self):
            for index, stage in enumerate(STAGES):
                with self.subTest(stage=stage):
                    result = supervise("blocking_" + stage.lower(), timings=(1.0, 1.2, 1.4, 2.0))
                    self.assertTrue(result["worker_reaped"])
                    self.assertTrue(result["termination_sent"])
                    if sys.platform != "win32":
                        self.assertTrue(result["kill_sent"])
                    self.assertEqual(result["stages"][stage]["outcome"], "TIMEOUT")
                    if stage == "HTTP":
                        self.assertIsNone(result["evidence"]["response_bytes"])
                        self.assertEqual(result["evidence"]["response_bytes_confirmed_min"], 0)
                    if stage == "XML":
                        self.assertGreater(result["evidence"]["response_bytes"], 0)
                    for earlier in STAGES[:index]:
                        self.assertEqual(result["stages"][earlier]["outcome"], "SUCCESS")
                    for later in STAGES[index + 1 :]:
                        self.assertEqual(result["stages"][later]["outcome"], "NOT_ATTEMPTED")
                    self.assertLess(result["elapsed_seconds"], 3.0)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    sink = io.StringIO()
    result = unittest.TextTestRunner(stream=sink).run(suite)
    return {
        "offline_self_check": "PASS" if result.wasSuccessful() else "FAILED",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }, result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--operator-authorized",
        action="store_true",
        help="Assert separate operator approval for this single live run",
    )
    parser.add_argument("--output", type=Path, help="Optional bounded JSON evidence file")
    args = parser.parse_args()
    if args.live and (not args.operator_authorized or not sys.platform.startswith("linux")):
        parser.error("live mode requires Linux and --operator-authorized")
    try:
        if args.live:
            result = supervise()
            success = result["evidence"].get("extraction") == "PASS" and result["worker_reaped"]
        else:
            result, success = self_check()
    except Exception:  # noqa: BLE001 -- fixed report instead of private traceback
        result, success = {"error": "diagnostic_failed"}, False
    data = encoded(result)
    if len(data) > OUTPUT_LIMIT:
        data, success = encoded({"error": "output_limit"}), False
    if args.output:
        # Fixed-size write; never append unbounded logs or raw response material.
        try:
            args.output.write_bytes(data)
        except OSError:
            data, success = encoded({"error": "evidence_write_failed"}), False
    sys.stdout.buffer.write(data)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
