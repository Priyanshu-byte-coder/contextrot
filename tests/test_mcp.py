import io
import json
from pathlib import Path

from contextrot.mcp import TOOLS, handle_message, serve

FIXTURES = Path(__file__).parent / "fixtures"


def _req(method, req_id=1, **params):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        msg["params"] = params
    return msg


def test_initialize_negotiates_protocol():
    resp = handle_message(_req("initialize", protocolVersion="2025-06-18"))
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "contextrot"
    assert "tools" in resp["result"]["capabilities"]
    # Unknown requested version falls back to the newest we support.
    resp = handle_message(_req("initialize", protocolVersion="2099-01-01"))
    assert resp["result"]["protocolVersion"] == "2025-06-18"


def test_notifications_get_no_response():
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping():
    assert handle_message(_req("ping"))["result"] == {}


def test_tools_list():
    resp = handle_message(_req("tools/list"))
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["rot_report", "agents_ranking", "prescriptions"]
    assert all("inputSchema" in t and t["description"] for t in TOOLS)


def test_tools_call_rot_report_on_fixtures():
    resp = handle_message(
        _req(
            "tools/call",
            name="rot_report",
            arguments={"days": 0, "data_dir": str(FIXTURES)},
        )
    )
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["sessions"] == 1
    assert payload["verdict"]["kind"] in {"rot", "edge", "clean", "insufficient"}
    assert "fresh_failure_rate" in payload


def test_tools_call_agents_ranking_on_fixtures():
    resp = handle_message(
        _req(
            "tools/call",
            name="agents_ranking",
            arguments={"days": 0, "data_dir": str(FIXTURES)},
        )
    )
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload["agents"], list)


def test_tools_call_unknown_tool_is_in_band_error():
    resp = handle_message(_req("tools/call", name="nope", arguments={}))
    assert resp["result"]["isError"] is True


def test_tool_exception_is_in_band_error():
    resp = handle_message(
        _req("tools/call", name="rot_report", arguments={"days": "not-a-number"})
    )
    assert resp["result"]["isError"] is True
    assert "content" in resp["result"]


def test_unknown_method_is_rpc_error():
    resp = handle_message(_req("resources/list"))
    assert resp["error"]["code"] == -32601


def test_serve_loop_newline_delimited():
    lines = "\n".join(
        [
            json.dumps(_req("initialize", req_id=0, protocolVersion="2025-06-18")),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "{broken json",
            json.dumps(_req("tools/list", req_id=1)),
        ]
    )
    out = io.StringIO()
    serve(stdin=io.StringIO(lines + "\n"), stdout=out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    # initialize, parse error, tools/list — the notification produced nothing.
    assert len(responses) == 3
    assert responses[0]["id"] == 0
    assert responses[1]["error"]["code"] == -32700
    assert responses[2]["id"] == 1
    assert all("\n" not in json.dumps(r) for r in responses)
