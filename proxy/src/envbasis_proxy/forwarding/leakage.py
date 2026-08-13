from __future__ import annotations

from collections.abc import AsyncIterator, Iterable


REDACTION = b"[REDACTED_CREDENTIAL]"


def redact_bytes(payload: bytes, secrets: Iterable[bytes]) -> bytes:
    redacted = payload
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTION)
    return redacted


async def redact_stream(
    chunks: AsyncIterator[bytes],
    *,
    secrets: Iterable[bytes],
    max_bytes: int,
) -> AsyncIterator[bytes]:
    secret_values = tuple(secret for secret in secrets if secret)
    keep = max((len(secret) - 1 for secret in secret_values), default=0)
    buffered = b""
    total = 0

    async for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError("Upstream response exceeded the configured size limit.")
        buffered += chunk
        buffered = redact_bytes(buffered, secret_values)
        if keep and len(buffered) > keep:
            split_at = len(buffered) - keep
            yield buffered[:split_at]
            buffered = buffered[split_at:]
        elif not keep:
            yield buffered
            buffered = b""

    if buffered:
        yield redact_bytes(buffered, secret_values)

