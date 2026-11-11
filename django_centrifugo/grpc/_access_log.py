from __future__ import annotations

import logging
import time


access_logger = logging.getLogger("django_centrifugo.grpc.access")
access_logger.addHandler(logging.NullHandler())


def _safe_target(target: str) -> str:
    # Targets come from the proxy and may contain control characters or be huge.
    return "".join(char if char.isprintable() and not char.isspace() else "?" for char in target[:128]) or "-"


def _log_access(
    operation: str,
    target: str,
    outcome: str,
    started: float,
    *,
    grpc_status: str,
    error_code: int | None = None,
) -> None:
    try:
        target = _safe_target(target)
        duration_ms = (time.monotonic() - started) * 1000
        level = logging.WARNING if outcome == "UNAUTHENTICATED" else logging.INFO
        code = f" code={error_code}" if error_code is not None else ""
        access_logger.log(
            level,
            "%s %s %s grpc=%s%s %.1fms",
            operation,
            target,
            outcome,
            grpc_status,
            code,
            duration_ms,
            extra={
                "operation": operation,
                "target": target,
                "outcome": outcome,
                "grpc_status": grpc_status,
                "error_code": error_code,
                "duration_ms": duration_ms,
            },
        )
    except Exception:  # noqa: BLE001, S110
        # A broken logging handler must not change the outcome of a proxy call.
        pass
