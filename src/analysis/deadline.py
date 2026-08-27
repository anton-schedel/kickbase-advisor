"""When the budget must be positive, and what it will be by then.

The budget only has to be ≥ 0 at the first kickoff of the matchday; after that
it may go negative again, because the lineup is locked. Both the briefing and
the lineup optimiser need that moment, so it lives here rather than in either.
"""

from datetime import datetime, timedelta

DAILY_LOGIN_BONUS = 100_000


def next_deadline(now: datetime) -> datetime:
    """First kickoff of the next matchday: Friday 20:30."""
    days_ahead = (4 - now.weekday()) % 7  # 4 = Friday
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=20, minute=30, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def login_bonus_before(deadline: datetime, now: datetime) -> int:
    """Login bonuses still collectable before the deadline."""
    return max(0, (deadline.date() - now.date()).days) * DAILY_LOGIN_BONUS


def spendable_at_deadline(budget: float | None, now: datetime | None = None) -> float:
    """Budget as it will stand at kickoff if nothing is bought or sold."""
    now = now or datetime.now()
    return (budget or 0) + login_bonus_before(next_deadline(now), now)


# Market values update daily at about this hour.
VALUE_UPDATE_HOUR = 22


def value_updates_before(deadline: datetime, now: datetime) -> int:
    """How many nightly value updates land between now and the deadline.

    A player sold before the deadline can be sold *after* those updates, so
    this is what a rising player is really worth as budget — pricing a forced
    sale at today's value understates it and can rule out the cheap way out.
    """
    count = 0
    stamp = now.replace(hour=VALUE_UPDATE_HOUR, minute=0, second=0, microsecond=0)
    if stamp <= now:
        stamp += timedelta(days=1)
    while stamp < deadline:
        count += 1
        stamp += timedelta(days=1)
    return count
