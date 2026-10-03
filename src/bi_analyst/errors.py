"""Safe errors: public messages never interpolate untrusted input."""


class BIError(Exception):
    def __init__(self, code: str, message: str, *, count: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.count = count

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "count": self.count}
