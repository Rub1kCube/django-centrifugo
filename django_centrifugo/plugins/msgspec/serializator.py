from typing import Any, ClassVar, Literal, get_args

import msgspec

from django_centrifugo.serialization.errors import ValidationIssue
from django_centrifugo.utils.type_inspection import is_none_type, is_safe_subclass, is_union, unwrap_annotation


class MsgspecSerializationBackend:
    """Validate msgspec Struct payloads using ``msgspec.convert``."""

    json_schema_generator_class: ClassVar[type[Any] | None] = None
    """No schema generator is provided by this integration."""

    def is_supported_annotation(self, annotation: Any) -> bool:
        """Accept Structs and unions of Structs and None, including Annotated."""
        model, _ = unwrap_annotation(annotation)
        if is_union(model):
            return all(is_none_type(part) or self.is_supported_annotation(part) for part in get_args(model))
        return is_safe_subclass(model, msgspec.Struct)

    def validate(self, annotation: Any, data: Any, *, from_attributes: bool | None = None) -> Any:
        """Convert and validate using msgspec's default strictness."""
        return msgspec.convert(data, type=annotation, from_attributes=bool(from_attributes))

    def to_python(
        self,
        instance: Any,
        *,
        mode: Literal["python", "json"],
        by_alias: bool = False,
        exclude_unset: bool = False,
    ) -> Any:
        """Convert values to builtins; msgspec does not expose unset tracking.

        Raises:
            NotImplementedError: If unset tracking or Python mode is requested.
        """
        if mode != "json" or exclude_unset:
            msg = "msgspec backend supports JSON mode without exclude_unset only"
            raise NotImplementedError(msg)
        if not by_alias and isinstance(instance, msgspec.Struct):
            fields = msgspec.structs.fields(type(instance))
            if any(item.name != item.encode_name for item in fields):
                msg = "msgspec backend cannot disable field aliases"
                raise NotImplementedError(msg)
        return msgspec.to_builtins(instance)

    def format_validation_error(self, error: Exception) -> tuple[ValidationIssue, ...]:
        """Return msgspec's single validation message without inventing a path."""
        if not isinstance(error, msgspec.ValidationError):
            raise TypeError(error)
        return (ValidationIssue(loc=(), message=str(error), type="validation_error"),)
