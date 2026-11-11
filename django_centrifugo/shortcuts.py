from __future__ import annotations

from typing import TYPE_CHECKING

from django_centrifugo.clients import create_async_client, create_client


if TYPE_CHECKING:
    import cent


__all__ = (
    "apublish",
    "publish",
)


def publish(
    channel: str,
    data: cent.JSON = None,
    *,
    b64data: str = "",
    skip_history: bool = False,
    tags: dict[str, str] | None = None,
    idempotency_key: str = "",
    delta: bool = False,
    version: int = 0,
    version_epoch: str = "",
    timeout: float | None = None,
) -> cent.PublishResult:
    """Publish using ``CENTRIFUGO_SETTINGS['client']``.

    Creates and closes a native pycent client for this call. For a series of
    publications, reuse a client from :func:`~django_centrifugo.clients.create_client`.
    Results and exceptions follow pycent; this function does not retry.

    Args:
        channel: Centrifugo channel name.
        data: JSON publication payload, following pycent's payload semantics.
        b64data: Base64-encoded binary payload, as an alternative to data.
        skip_history: Publish without saving to channel history.
        tags: Server-side publication tags.
        idempotency_key: Server-side deduplication key, reused for retries of
            the same publication when the broker supports deduplication.
        delta: Enable delta compression for the publication.
        version: Publication version for channels using version checks.
        version_epoch: Scope for publication versions that may restart.
        timeout: Per-call timeout in seconds, overriding ``request_timeout``.

    Returns:
        The native pycent publication result, including its stream position.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If client settings are
            missing or invalid.
        cent.CentError: If validation, transport, or server processing fails.
    """
    with create_client() as client:
        return client.publish(
            channel=channel,
            data=data,
            b64data=b64data,
            skip_history=skip_history,
            tags=tags,
            idempotency_key=idempotency_key,
            delta=delta,
            version=version,
            version_epoch=version_epoch,
            timeout=timeout,
        )


async def apublish(
    channel: str,
    data: cent.JSON = None,
    *,
    b64data: str = "",
    skip_history: bool = False,
    tags: dict[str, str] | None = None,
    idempotency_key: str = "",
    delta: bool = False,
    version: int = 0,
    version_epoch: str = "",
    timeout: float | None = None,  # noqa: ASYNC109 - per-request override matches pycent
) -> cent.PublishResult:
    """Publish asynchronously using ``CENTRIFUGO_SETTINGS['client']``.

    Creates and closes a native pycent client for this call. For a series of
    publications, reuse a client from :func:`~django_centrifugo.clients.create_async_client`.
    Results and exceptions follow pycent; this function does not retry.

    Args:
        channel: Centrifugo channel name.
        data: JSON publication payload, following pycent's payload semantics.
        b64data: Base64-encoded binary payload, as an alternative to data.
        skip_history: Publish without saving to channel history.
        tags: Server-side publication tags.
        idempotency_key: Server-side deduplication key, reused for retries of
            the same publication when the broker supports deduplication.
        delta: Enable delta compression for the publication.
        version: Publication version for channels using version checks.
        version_epoch: Scope for publication versions that may restart.
        timeout: Per-call timeout in seconds, overriding ``request_timeout``.

    Returns:
        The native pycent publication result, including its stream position.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If client settings are
            missing or invalid.
        cent.CentError: If validation, transport, or server processing fails.
    """
    async with create_async_client() as client:
        return await client.publish(
            channel=channel,
            data=data,
            b64data=b64data,
            skip_history=skip_history,
            tags=tags,
            idempotency_key=idempotency_key,
            delta=delta,
            version=version,
            version_epoch=version_epoch,
            timeout=timeout,
        )
