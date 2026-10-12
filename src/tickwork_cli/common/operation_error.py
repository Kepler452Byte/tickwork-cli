from tickwork_cli.common.application_errors import TickworkError


class OperationError(TickworkError):
    def __init__(self, message: str, code: str, exit_code: int = 1):
        super().__init__(code, message)
        self.exit_code = exit_code
