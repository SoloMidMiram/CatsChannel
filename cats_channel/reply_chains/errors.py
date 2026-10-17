"""Safe allowlisted domain failures; never include IDs, tokens or SQL."""

ERROR_CODES = frozenset(
    {
        "reply_thread_not_found",
        "reply_submission_not_found",
        "reply_parent_not_found",
        "reply_parent_cross_thread",
        "reply_intent_conflict",
        "reply_chain_invalid_state",
        "reply_chain_conflict",
        "reply_token_invalid",
        "reply_parent_unpublished",
        "reply_intent_not_found",
        "reply_chain_unavailable",
    }
)


class ReplyChainError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "reply_chain_unavailable"
        super().__init__(self.code)
