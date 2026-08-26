class GatewayError(Exception):
    """An error with a safe, stable public representation."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(code)


class ProviderError(Exception):
    """Provider payloads and credentials must never enter exception messages."""

    def __init__(self, code: str, transient: bool = False, retry_after: float = 0) -> None:
        self.code, self.transient, self.retry_after = code, transient, retry_after
        super().__init__(code)
