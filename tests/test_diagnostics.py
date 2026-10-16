import json
import logging

from cats_channel.diagnostics import (
    classify_exception,
    configure_logging,
    diagnostic_rule,
    exception_chain,
    log_failure,
    safe_log_analysis,
)
from cats_channel.errors import MediaError


def rules():
    return (
        diagnostic_rule("api_credentials", "configuration", "login", "high", r"^ApiId.*Error$"),
        diagnostic_rule("flood", "remote_policy", "login", "high", r"Flood"),
        diagnostic_rule("proxy", "network", "connection", "medium", r"Proxy|Connection"),
    )


def test_ordered_regex_rules_keep_specific_error_and_all_signals():
    error_type = type("ApiIdPublishedFloodError", (Exception,), {})
    code, analysis = classify_exception(
        error_type("private API value"),
        rules(),
        phase="login",
        default_code="unknown",
        default_category="unknown",
    )
    assert code == "api_credentials"
    assert analysis["signals"] == ["api_credentials", "flood"]
    assert analysis["exception_types"] == ["ApiIdPublishedFloodError"]
    assert analysis["raw_log_included"] is False


def test_classifier_iterates_over_nested_exception_chain():
    proxy_type = type("ProxyConnectionError", (Exception,), {})
    inner = proxy_type("socks5h://user:password@private-host:10808")
    outer = RuntimeError("wrapper contains private account data")
    outer.__cause__ = inner
    code, analysis = classify_exception(
        outer,
        rules(),
        phase="login",
        default_code="unknown",
        default_category="unknown",
    )
    assert code == "proxy"
    assert analysis["exception_types"] == ["RuntimeError", "ProxyConnectionError"]
    assert analysis["exception_chain_truncated"] is False
    assert "private" not in json.dumps(analysis)


def test_exception_chain_is_cycle_safe_and_bounded():
    error = RuntimeError("private")
    error.__cause__ = error
    names, truncated = exception_chain(error, max_depth=3)
    assert names == ("RuntimeError",)
    assert truncated is True


def test_safe_log_analysis_drops_unknown_and_sensitive_fields():
    safe = safe_log_analysis(
        {
            "primary": "network_connect",
            "phase": "login",
            "signals": ["network_connect"],
            "raw_log": "token=private-secret-value",
            "proxy_url": "socks5h://private-host:10808",
            "raw_log_included": True,
        }
    )
    assert safe == {
        "primary": "network_connect",
        "phase": "login",
        "signals": ["network_connect"],
        "raw_log_included": False,
    }


def test_json_logger_never_serializes_exception_message_or_unknown_analysis(capsys):
    logger = configure_logging("ERROR")
    error = MediaError(
        "phone=private token=private-secret-value",
        code="telegram_connect",
        log_analysis={
            "primary": "telegram_connect",
            "phase": "login",
            "exception_types": ["ProxyConnectionError"],
            "unsafe": "private-secret-value",
        },
    )
    log_failure(logger, "telegram_login_failed", error, operation="telegram_login")
    output = capsys.readouterr()
    assert output.out == ""
    record = json.loads(output.err)
    assert record["event"] == "telegram_login_failed"
    assert record["code"] == "telegram_connect"
    assert record["operation"] == "telegram_login"
    assert record["analysis"]["exception_types"] == ["ProxyConnectionError"]
    assert record["analysis"]["raw_log_included"] is False
    assert "private" not in output.err


def test_logger_failure_never_replaces_primary_operational_error():
    class BrokenLogger(logging.Logger):
        def error(self, msg, *args, **kwargs):
            raise OSError("private logging destination")

    original = MediaError("private operational detail", code="telegram_connect")
    assert log_failure(BrokenLogger("broken"), "operation_failed", original) is None


def test_cli_unexpected_failure_logs_safe_json_and_keeps_stdout_contract(monkeypatch, capsys):
    from unittest.mock import patch

    from cats_channel.cli import main
    from cats_channel.config import Settings

    monkeypatch.setattr("sys.argv", ["cats-channel", "--list-downloads"])
    with (
        patch("cats_channel.cli.Settings", return_value=Settings(_env_file=None)),
        patch(
            "cats_channel.cli.list_downloads",
            side_effect=RuntimeError("token=private-secret phone=private-phone"),
        ),
    ):
        assert main() == 1
    output = capsys.readouterr()
    response = json.loads(output.out)
    record = json.loads(output.err)
    assert response["error"]["code"] == "internal_error"
    assert record["event"] == "cli_failure"
    assert record["operation"] == "list_downloads"
    assert record["analysis"]["exception_types"] == ["RuntimeError"]
    assert "private" not in output.out + output.err
