"""Rule-based category and priority for new tickets.

Deliberately simple and explainable: keyword lists, documented here, that an agent can
always override on the ticket. No AI involved, so the result is predictable.
"""

import re

from app.models.ticket import EscalationReason, TicketCategory, TicketPriority

CATEGORY_KEYWORDS: dict[TicketCategory, tuple[str, ...]] = {
    TicketCategory.BILLING: (
        "refund", "charge", "payment", "invoice", "bill", "subscription", "price", "plan",
        "cancel", "money", "paid", "pay",
    ),
    TicketCategory.ACCOUNT: (
        "password", "login", "log in", "sign in", "account", "email", "two-factor", "2fa",
        "locked out", "username",
    ),
    TicketCategory.TECHNICAL: (
        "error", "bug", "crash", "not working", "doesn't work", "won't", "connect", "wifi",
        "wi-fi", "offline", "firmware", "reset", "setup", "app",
    ),
    TicketCategory.PRODUCT: (
        "product", "device", "camera", "hub", "sensor", "warranty", "compatible", "shipping",
        "delivery", "order", "package",
    ),
}

URGENT_KEYWORDS = (
    "urgent", "emergency", "fraud", "stolen", "hacked", "security breach", "unauthorized",
    "unauthorised", "charged twice", "double charged", "identity theft",
)
HIGH_KEYWORDS = (
    "asap", "immediately", "complaint", "lawyer", "damaged", "broken", "lost", "never arrived",
    "not delivered", "still waiting",
)


def _count(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if re.search(rf"\b{re.escape(keyword)}", text))


def categorize(text: str) -> TicketCategory:
    lowered = text.lower()
    scores = {category: _count(lowered, words) for category, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=lambda category: scores[category])
    return best if scores[best] > 0 else TicketCategory.GENERAL


def prioritize(text: str, reason: EscalationReason | None = None) -> TicketPriority:
    lowered = text.lower()
    if _count(lowered, URGENT_KEYWORDS):
        return TicketPriority.URGENT
    if _count(lowered, HIGH_KEYWORDS):
        return TicketPriority.HIGH
    if reason == EscalationReason.PROVIDER_FAILURE:
        # The customer got no answer at all through no fault of their own.
        return TicketPriority.HIGH
    return TicketPriority.MEDIUM
