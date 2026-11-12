from typing import Any, ClassVar, Literal, Protocol

from typing_extensions import TypeForm

from django_centrifugo.serialization.errors import ValidationIssue


class SerializationBackend(Protocol):
    """Validate action payloads and convert results to Python values."""

    json_schema_generator_class: ClassVar[type[Any] | None]

    def is_supported_annotation(self, annotation: TypeForm[Any]) -> bool:
        """Return whether this backend supports the payload annotation."""
        ...

    def validate(self, annotation: TypeForm[Any], data: Any, *, from_attributes: bool | None = None) -> Any:
        """Validate data against an annotation and return the resulting object."""
        ...

    def to_python(
        self, instance: Any, *, mode: Literal["python", "json"], by_alias: bool = False, exclude_unset: bool = False
    ) -> Any:
        """Convert a result to Python values without encoding a JSON document."""
        ...

    def format_validation_error(self, error: Exception) -> tuple[ValidationIssue, ...]:
        """Normalize a backend validation error, or raise TypeError if unrelated."""
        ...
