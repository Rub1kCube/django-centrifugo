Documentation guidelines
========================

Documentation is part of the public API. A change to public behavior is complete
only when the relevant docstrings, guides, API reference, and examples agree with
the implementation and ``just docs-check`` passes.

Choose the right location
-------------------------

Use each documentation layer for a distinct purpose:

* Docstrings define the contract of a module, class, function, method, or
  attribute.
* Usage guides explain tasks and connect multiple APIs into practical workflows.
* The API reference lists public objects and their signatures.
* Code comments explain non-obvious implementation decisions and constraints.

Do not copy the same explanation into several layers. Link to the canonical
explanation instead.

Public API docstrings
---------------------

Use Google-style docstrings. Keep parameter and return types in Python annotations;
Sphinx adds them to the rendered documentation. Start with a short summary, then
describe behavior or constraints that are not obvious from the signature.

Include ``Args``, ``Returns``, ``Yields``, and ``Raises`` only when applicable.
Document side effects, accepted value ranges, exception conditions, and important
state changes. Avoid descriptions that merely repeat an identifier.

For example:

.. code-block:: python

   def load_config(path: Path) -> Config:
       """Load configuration from a file.

       Args:
           path: Configuration file to read.

       Returns:
           Parsed configuration.

       Raises:
           ConfigurationError: If the file cannot be read or parsed.

       Examples:
           >>> config = load_config(Path("config.toml"))
           >>> config.debug
           False
       """

Document every new or changed public object. Private helpers normally need no API
documentation, but their comments should capture important implementation reasons
or invariants.

References
----------

Use Sphinx roles instead of plain text when referring to documented objects or
pages. The most common roles are ``:class:`target```, ``:func:`target```,
``:meth:`target```, ``:attr:`target```, and ``:doc:`target```. Use a fully
qualified target when a short name could be ambiguous. Prefix a Python target with
``~`` when the rendered label should show only its final component, for example
``:class:`~package.module.Type```.

Keep ``nitpicky`` references valid. Do not suppress a missing-reference warning
unless the referenced object genuinely cannot be linked.

Examples and doctests
---------------------

Use ``.. doctest::`` for small, deterministic examples that should be executed as
part of ``just docs-check``:

.. doctest::

   >>> sorted({"beta", "alpha"})
   ['alpha', 'beta']

Use ``.. code-block::`` when an example requires network access, external services,
nondeterministic values, secrets, or extensive setup. Keep such examples realistic
and make any omitted setup explicit.

For examples that represent a file, use a caption with the filename and a
language icon. The same caption option works with ``literalinclude``:

.. code-block:: rst

   .. code-block:: python
      :caption: :iconify:`devicon:python` example.py

      print("Hello!")

API and navigation updates
--------------------------

When adding a public module, class, or function, update
``docs/pages/api-reference.rst`` so autodoc renders it. Add new guide pages to a
``toctree``; otherwise Sphinx treats them as orphaned documents. Keep guides focused
on user tasks rather than mirroring the source tree.

Verification
------------

Run these commands from the repository root:

.. code-block:: console

   just docs
   just docs-check

The strict check builds HTML with warnings treated as errors and executes doctests.
Run ``just docs-linkcheck`` after adding or changing external links. Never edit or
commit generated files under ``docs/_build/``.
