from typing import Any, ClassVar, Literal, cast, get_args

from pydantic import BaseModel, TypeAdapter, ValidationError
from typing_extensions import TypeForm

from django_centrifugo.serialization.errors import ValidationIssue
from django_centrifugo.utils.type_inspection import (
    cache_annotation,
    is_none_type,
    is_safe_subclass,
    is_union,
    unwrap_annotation,
)


@cache_annotation
def _adapter(annotation: TypeForm[Any]) -> TypeAdapter[Any]:
    return TypeAdapter(annotation)


class PydanticSerializationBackend:
    """Validate Pydantic models through their public API."""

    json_schema_generator_class: ClassVar[type[Any] | None] = None
    """No schema generator is provided by this integration."""

    def is_supported_annotation(self, annotation: TypeForm[Any]) -> bool:
        """Accept models and unions of models and None, including Annotated."""
        model, _ = unwrap_annotation(annotation)
        if is_union(model):
            return all(is_none_type(part) or self.is_supported_annotation(part) for part in get_args(model))
        return is_safe_subclass(model, BaseModel)

    def validate(
        self,
        annotation: TypeForm[Any],
        data: Any,
        *,
        from_attributes: bool | None = None,
    ) -> Any:
        """Validate data, making the original payload available as context."""
        return _adapter(annotation).validate_python(data, from_attributes=from_attributes, context=data)

    def to_python(
        self,
        instance: Any,
        *,
        mode: Literal["python", "json"],
        by_alias: bool = False,
        exclude_unset: bool = False,
    ) -> Any:
        """Convert model instances or other supported values to Python data."""
        return TypeAdapter(Any).dump_python(instance, mode=mode, by_alias=by_alias, exclude_unset=exclude_unset)

    def format_validation_error(self, error: Exception) -> tuple[ValidationIssue, ...]:
        """Normalize Pydantic errors without including raw input values."""
        if not isinstance(error, ValidationError):
            raise TypeError(error)
        return tuple(
            ValidationIssue(
                loc=tuple(item["loc"]), message=item["msg"], type=item["type"], params=dict(item.get("ctx") or {})
            )
            for item in cast("Any", error).errors(include_url=False, include_input=False)
        )
