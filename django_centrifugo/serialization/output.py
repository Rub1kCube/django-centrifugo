from typing import Any, get_args

from django_centrifugo.serialization.base import SerializationBackend
from django_centrifugo.utils.type_inspection import is_union, model_annotation


def _output_model(annotation: Any, backend: SerializationBackend) -> Any | None:
    if backend.is_supported_annotation(annotation):
        return annotation

    if is_union(annotation):
        members = get_args(annotation)
        models = [part for part in members if backend.is_supported_annotation(part)]
        if len(members) == 2 and len(models) == 1 and dict[str, object] in members:  # noqa: PLR2004
            return models[0]
    return None


def _validate_output(backend: SerializationBackend, annotation: Any, result: Any) -> Any:
    if result is None and model_annotation(annotation)[1]:
        backend.validate(annotation, None)
        return None

    if backend.is_supported_annotation(type(result)):
        result = backend.to_python(result, mode="json", by_alias=True)

    if not isinstance(result, dict):
        msg = "Output must be a model instance or dictionary"
        raise TypeError(msg)

    validated = backend.validate(annotation, result)
    return backend.to_python(validated, mode="json", by_alias=True)
