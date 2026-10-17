"""Stable typed failures raised by persistence contracts."""


class PersistenceError(RuntimeError):
    code = "persistence"


class ThreadNotFoundError(PersistenceError):
    code = "thread_not_found"


class SubmissionNotFoundError(PersistenceError):
    code = "submission_not_found"


class PostNotFoundError(PersistenceError):
    code = "post_not_found"


class MissingParentError(PersistenceError):
    code = "missing_parent"


class CrossThreadParentError(PersistenceError):
    code = "cross_thread_parent"


class InvalidThreadStateError(PersistenceError):
    code = "invalid_thread_state"


class ConcurrentThreadUpdateError(PersistenceError):
    code = "concurrent_thread_update"


class DuplicateSourceMediaError(PersistenceError):
    code = "duplicate_source_media"


class DuplicatePostSubmissionError(PersistenceError):
    code = "duplicate_post_submission"


class DuplicateTelegramMessageError(PersistenceError):
    code = "duplicate_telegram_message"
