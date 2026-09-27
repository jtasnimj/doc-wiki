class AppError(Exception):
    """Safe public errors: never wrap provider messages or document contents."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
