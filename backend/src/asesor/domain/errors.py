class DomainError(Exception):
    code = "DOMAIN_ERROR"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConsentRequiredError(DomainError):
    code = "CONSENT_REQUIRED"

    def __init__(self) -> None:
        super().__init__(
            "Contact data (phone or email) requires contact_consent=true in the same call"
        )


class EmptyUpdateError(DomainError):
    code = "EMPTY_UPDATE"

    def __init__(self) -> None:
        super().__init__("At least one lead field must be provided")


class InvalidPhoneError(DomainError):
    code = "INVALID_PHONE"
