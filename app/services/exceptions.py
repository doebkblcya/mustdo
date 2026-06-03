class TodoAnalyzerError(Exception):
    code = "todo_analyzer_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AIProviderConfigError(TodoAnalyzerError):
    code = "provider_not_configured"


class AIProviderError(TodoAnalyzerError):
    code = "model_failed"


class InvalidModelOutputError(TodoAnalyzerError):
    code = "invalid_model_output"
