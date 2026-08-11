"""Select bounded, complete conversation turns for model requests."""

from __future__ import annotations

from collections.abc import Sequence

from .models import Message, MessageRole, ModelMessage


def select_recent_history(
    messages: Sequence[Message],
    *,
    max_characters: int,
) -> list[ModelMessage]:
    """Return the newest complete user/assistant turns within a character budget."""

    if max_characters <= 0:
        return []

    complete_turns: list[tuple[Message, Message]] = []
    pending_user: Message | None = None
    for message in messages:
        if message.role == MessageRole.USER:
            pending_user = message
        elif (
            message.role == MessageRole.ASSISTANT
            and pending_user is not None
            and pending_user.content
            and message.content
        ):
            complete_turns.append((pending_user, message))
            pending_user = None

    selected_turns: list[tuple[Message, Message]] = []
    used_characters = 0
    for user_message, assistant_message in reversed(complete_turns):
        turn_characters = len(user_message.content) + len(
            assistant_message.content
        )
        if used_characters + turn_characters > max_characters:
            break
        selected_turns.append((user_message, assistant_message))
        used_characters += turn_characters

    history: list[ModelMessage] = []
    for user_message, assistant_message in reversed(selected_turns):
        history.extend(
            [
                ModelMessage(
                    role=MessageRole.USER,
                    content=user_message.content,
                ),
                ModelMessage(
                    role=MessageRole.ASSISTANT,
                    content=assistant_message.content,
                ),
            ]
        )
    return history
