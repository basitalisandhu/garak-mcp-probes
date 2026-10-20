"""The dry-run fake server: planted notes, the send_report log and the read_note error path."""

from __future__ import annotations

import asyncio
import json

import pytest

from garak_mcp_probes import fake_server


def _call(server, tool: str, args: dict):
    from mcp import Client

    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(go())


def _text(result) -> str:
    return "".join(getattr(b, "text", "") for b in result.content)


def test_default_notes_without_the_environment_variable(monkeypatch):
    monkeypatch.delenv("GARAK_MCP_FAKE_NOTES", raising=False)
    notes = fake_server.load_notes()
    assert notes == fake_server.DEFAULT_NOTES and notes is not fake_server.DEFAULT_NOTES


def test_planted_notes_from_a_file(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"a": "alpha", "b": "beta"}), encoding="utf-8")
    monkeypatch.setenv("GARAK_MCP_FAKE_NOTES", str(path))
    assert fake_server.load_notes() == {"a": "alpha", "b": "beta"}


@pytest.mark.parametrize("content", [["not", "an", "object"], {"a": 1}])
def test_planted_notes_must_be_an_object_of_strings(tmp_path, monkeypatch, content):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setenv("GARAK_MCP_FAKE_NOTES", str(path))
    with pytest.raises(SystemExit, match="expected a JSON object"):
        fake_server.load_notes()


def test_send_report_writes_the_log_file(tmp_path, monkeypatch):
    log = tmp_path / "sent.jsonl"
    monkeypatch.setenv("GARAK_MCP_FAKE_LOG", str(log))
    fake_server.SENT.clear()
    result = _call(fake_server.build_server({}), "send_report", {"recipient": "r", "body": "hello"})
    assert "nothing was sent" in _text(result)
    entry = {"recipient": "r", "body_chars": 5, "body": "hello"}
    assert [entry] == fake_server.SENT
    assert [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] == [entry]


def test_read_note_unknown_name_is_an_error_result():
    result = _call(fake_server.build_server({"x": "text"}), "read_note", {"name": "missing"})
    assert result.is_error and "no note named 'missing'" in _text(result)
    ok = _call(fake_server.build_server({"x": "text"}), "read_note", {"name": "x"})
    assert not ok.is_error and _text(ok) == "text"
