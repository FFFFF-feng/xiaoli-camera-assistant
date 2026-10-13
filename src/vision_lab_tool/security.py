"""Defense at the persistence/export boundary; requests and headers are never recorded."""

import re
from collections.abc import Mapping

SENSITIVE_FIELDS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "headers",
    "x-api-key",
    "x-goog-api-key",
    "inlinedata",
    "image_url",
    "data_url",
}


def scrub(value, secrets=()):
    if isinstance(value, Mapping):
        return {
            str(k): ("[REDACTED]" if str(k).lower() in SENSITIVE_FIELDS else scrub(v, secrets))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(
            r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=\r\n]+",
            "[IMAGE REDACTED]",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"(?i)Bearer\s+[^\s\"\x27,}]+", "Bearer [REDACTED]", value)
        value = re.sub(
            r"(?i)(authorization|api[_-]?key|x-goog-api-key|x-api-key)"
            r"([\"\x27]?\s*[:=]\s*[\"\x27]?)[^\s\"\x27,}]+",
            r"\1\2[REDACTED]",
            value,
        )
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
        return value
    return value
