from django_centrifugo.serialization.errors import ValidationIssue


class ActionError(Exception):
    """An expected action dispatch error."""


class UnknownActionError(ActionError):
    """The requested action is not registered."""


class PayloadValidationError(ActionError):
    """An action payload did not pass backend validation.

    Attributes:
        issues: Normalized backend validation issues.
    """

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        super().__init__("Invalid action payload")
        self.issues = issues
