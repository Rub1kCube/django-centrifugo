type Output[T] = T | dict[str, object]
"""Annotate a result that may be either a model instance or a dictionary.

RPC and stream handlers validate returned values against ``T`` when it is a
model supported by the selected backend. A method that always returns a model
may annotate that model directly; use ``None`` for an RPC without data.
"""
