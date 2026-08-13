from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from envbasis_proxy.forwarding.leakage import redact_stream

from conftest import OPENAI_KEY, UpstreamRecorder


def test_oversized_request_is_rejected_before_forwarding(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/openai/v1/responses",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=b"x" * 5000,
    )

    assert response.status_code == 413
    assert recorder.requests == []


def test_stream_redaction_handles_credential_split_across_chunks() -> None:
    async def chunks():
        encoded = OPENAI_KEY.encode()
        yield b'{"key":"' + encoded[:8]
        yield encoded[8:15]
        yield encoded[15:] + b'"}'

    async def collect() -> bytes:
        output = b""
        async for chunk in redact_stream(
            chunks(),
            secrets=(OPENAI_KEY.encode(),),
            max_bytes=1024,
        ):
            output += chunk
        return output

    output = asyncio.run(collect())
    assert OPENAI_KEY.encode() not in output
    assert b"REDACTED_CREDENTIAL" in output

