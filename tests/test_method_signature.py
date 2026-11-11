from __future__ import annotations

import inspect

import pytest

from django_centrifugo.utils.type_inspection import MethodSignature


class Payload:
    pass


def function(data: Payload, ignored: MissingType) -> Payload:  # type: ignore[name-defined]  # noqa: F821
    return data


def generic_function[T](data: T) -> T:
    return data


class Parent[T]:
    def method(self, data: T) -> T:
        return data


class Child(Parent[Payload]):
    pass


@pytest.mark.parametrize("positional", [True, False])
def test_inspect_function_without_class(positional: bool) -> None:
    names = {"data", "return"}
    signature = (
        MethodSignature.from_method(function, annotation_names=names)
        if positional
        else MethodSignature.from_method(method=function, annotation_names=names)
    )

    assert signature.signature == inspect.signature(function)
    assert signature.annotations == {"data": Payload, "return": Payload}
    assert signature.bindings == {}


def test_inspect_generic_function_without_class() -> None:
    signature = MethodSignature.from_method(generic_function)
    parameter = generic_function.__type_params__[0]

    assert signature.annotations == {"data": parameter, "return": parameter}
    assert signature.bindings == {}


def test_inspect_method_with_concrete_class() -> None:
    signature = MethodSignature.from_method(Parent.method, target_class=Child)

    assert signature.annotations == {"data": Payload, "return": Payload}
    assert signature.bindings == {Parent.__type_params__[0]: Payload}


def test_inspect_requires_function() -> None:
    assert inspect.signature(MethodSignature.from_method).parameters["method"].default is inspect.Parameter.empty
