from edge.publisher import publish_event


def test_publish_does_not_use_the_python_client_signature(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class Response:
        status = 204

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request, timeout: float = 0) -> Response:
        seen["user_agent"] = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr("edge.publisher.urlopen", fake_urlopen)
    publish_event("https://site.spiderolt.com/api/snmp-trap/traps", "edge_abc", {"source": "snmp_trap"})

    assert seen["user_agent"] == "SpiderOLT-snmp-trap/1.0"
    assert "Python-urllib" not in seen["user_agent"]
