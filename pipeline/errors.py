"""Problems the user can understand and fix themselves. The backend shows their message as-is
(no technical error type), unlike unexpected bugs."""


class PipelineUserError(Exception):
    pass


class RepoNotFound(PipelineUserError):
    """The repository doesn't exist, is private, or GitHub can't be reached."""


class NoSourceFiles(PipelineUserError):
    """The repository has no source files the model can analyse (currently: Python)."""
