"""CRM and support mocks, so the sales and support profiles are real rather than decorative.

Thinner than the devops estate on purpose. The flagship demo is devops, and the job of this module
is to prove that profile switching changes the agent's world rather than only its prompt -- if the
brain only ever ran against one vertical, "configurable" would be a claim rather than a property.

The interesting difference from devops is what the confirm tier guards. For an SRE the irreversible
action is a rollback; here it is a sent message or a refund, which is why `send_email`,
`send_reply` and `issue_refund` are all `confirm` and `destructive`, and why `issue_refund` carries
a policy ceiling rather than a technical limit.
"""

from __future__ import annotations

from typing import Any, Mapping

from brain.contracts import ToolResult
from brain.errors import ErrorClass

NOW = "2026-03-14T09:12:00Z"
REFUND_CEILING_USD = 250.0


def _accounts() -> dict[str, dict[str, Any]]:
    return {
        "northwind": {
            "id": "acc-4471",
            "name": "Northwind Logistics",
            "segment": "enterprise",
            "owner": "Dana Okafor",
            "arr_usd": 184000,
            "renewal_date": "2026-06-30",
            "products": ["Fleet API", "Route Optimiser", "SSO"],
            "health_score": 62,
            "stakeholders": [
                {"name": "Ingrid Halvorsen", "role": "VP Engineering", "influence": "decision_maker", "last_contacted_at": "2026-03-11T15:00:00Z"},
                {"name": "Tomasz Wojcik", "role": "Platform Lead", "influence": "technical_evaluator", "last_contacted_at": "2026-03-13T09:30:00Z"},
                {"name": "Priyanka Menon", "role": "Procurement", "influence": "gatekeeper", "last_contacted_at": "2026-02-27T11:00:00Z"},
            ],
        },
        "meridian": {
            "id": "acc-5092",
            "name": "Meridian Health Systems",
            "segment": "enterprise",
            "owner": "Dana Okafor",
            "arr_usd": 412000,
            "renewal_date": "2026-04-15",
            "products": ["Fleet API", "Audit Log", "HIPAA Addendum"],
            "health_score": 38,
            "stakeholders": [
                {"name": "Dr Amara Nwosu", "role": "CIO", "influence": "decision_maker", "last_contacted_at": "2026-03-06T14:00:00Z"},
                {"name": "Kenji Watanabe", "role": "Security Architect", "influence": "blocker", "last_contacted_at": "2026-03-12T10:15:00Z"},
            ],
        },
    }


def _deals() -> list[dict[str, Any]]:
    return [
        {
            "id": "deal-8813",
            "account_id": "acc-4471",
            "name": "Northwind -- Route Optimiser expansion",
            "stage": "negotiation",
            "amount_usd": 96000,
            "close_date": "2026-04-10",
            "owner": "Dana Okafor",
            "last_activity_at": "2026-03-13T09:30:00Z",
            "competitors": ["Onfleet"],
            "objections": [
                "Per-vehicle pricing does not scale past 400 vehicles",
                "Wants SSO provisioning before signature",
                "Asked twice about the 2026 roadmap for dispatch automation",
            ],
        },
        {
            "id": "deal-8702",
            "account_id": "acc-5092",
            "name": "Meridian -- Audit Log renewal",
            "stage": "evaluation",
            "amount_usd": 412000,
            "close_date": "2026-04-15",
            "owner": "Dana Okafor",
            "last_activity_at": "2026-03-12T10:15:00Z",
            "competitors": [],
            "objections": [
                "Security review flagged audit-log retention defaults",
                "Needs a signed BAA before legal will proceed",
            ],
        },
    ]


def _customers() -> dict[str, dict[str, Any]]:
    return {
        "meridian": {
            "id": "cus-5092",
            "name": "Meridian Health Systems",
            "plan": "Enterprise",
            "tenure_months": 27,
            "entitlements": ["24x7 support", "4h P1 response", "named CSM", "HIPAA addendum"],
            "environment": "self-hosted, v3.4.1, us-east",
            "sentiment_trend": "sharply_negative",
            "csm": "Lea Fontaine",
            "open_tickets": [
                {
                    "id": "SUP-91844",
                    "subject": "Bulk export fails since Tuesday",
                    "opened_at": "2026-03-12T08:20:00Z",
                    "status": "open",
                }
            ],
        },
        "brightline": {
            "id": "cus-6120",
            "name": "Brightline Freight",
            "plan": "Growth",
            "tenure_months": 6,
            "entitlements": ["business hours support", "next-business-day response"],
            "environment": "cloud, us-west",
            "sentiment_trend": "neutral",
            "csm": None,
            "open_tickets": [],
        },
    }


def _tickets() -> list[dict[str, Any]]:
    return [
        {
            "id": "SUP-91844",
            "customer_id": "cus-5092",
            "subject": "Bulk export fails since Tuesday",
            "status": "open",
            "priority": "high",
            "opened_at": "2026-03-12T08:20:00Z",
            "resolved_at": None,
            "tags": ["export", "regression"],
            "resolution_note": "",
            "reopened_count": 0,
        },
        {
            "id": "SUP-90210",
            "customer_id": "cus-5092",
            "subject": "Audit log retention shorter than documented",
            "status": "resolved",
            "priority": "medium",
            "opened_at": "2026-02-14T13:05:00Z",
            "resolved_at": "2026-02-20T16:40:00Z",
            "tags": ["audit", "docs"],
            "resolution_note": (
                "Documentation was wrong, not the product: default retention is 90 days in "
                "self-hosted deployments. Docs corrected in v3.4.2. Customer was offered a config "
                "change to extend to 400 days and accepted."
            ),
            "reopened_count": 1,
        },
        {
            "id": "SUP-88771",
            "customer_id": "cus-6120",
            "subject": "How do I rotate API keys?",
            "status": "closed",
            "priority": "low",
            "opened_at": "2026-01-30T09:00:00Z",
            "resolved_at": "2026-01-30T10:12:00Z",
            "tags": ["how-to"],
            "resolution_note": "Pointed to the key rotation guide.",
            "reopened_count": 0,
        },
    ]


def _known_issues() -> list[dict[str, Any]]:
    return [
        {
            "id": "KI-3391",
            "title": "Bulk export fails for deployments over 2M records",
            "symptoms": ["export fails", "bulk export", "timeout on export"],
            "affected_versions": ["3.4.0", "3.4.1"],
            "workaround": (
                "Export in date-bounded batches under 500k records, or apply the 3.4.2 patch."
            ),
            "fix_version": "3.4.2",
            "status": "fixed",
            "updated_at": "2026-03-13T17:00:00Z",
        },
        {
            "id": "KI-3410",
            "title": "Audit log retention default differs from documentation",
            "symptoms": ["audit retention", "audit log", "logs missing"],
            "affected_versions": ["<3.4.2"],
            "workaround": "Set AUDIT_RETENTION_DAYS explicitly; the default is 90.",
            "fix_version": "3.4.2",
            "status": "fixed",
            "updated_at": "2026-02-20T16:40:00Z",
        },
    ]


class World:
    """Mutable CRM and support state, shared by both providers in this module."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.accounts = _accounts()
        self.deals = _deals()
        self.customers = _customers()
        self.tickets = _tickets()
        self.issues = _known_issues()
        self.activities: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []


_WORLD = World()


def world() -> World:
    return _WORLD


class CrmMock:
    """Accounts, pipeline, activity logging, drafting and sending."""

    def __init__(self, w: World) -> None:
        self._w = w

    def invoke(self, method: str, args: dict[str, Any]) -> ToolResult:
        handler = getattr(self, method, None)
        if handler is None or method.startswith("_"):
            return ToolResult.failure(ErrorClass.UNKNOWN_TOOL, f"crm has no method {method!r}")
        return handler(args)

    def get_account(self, args: Mapping[str, Any]) -> ToolResult:
        wanted = str(args.get("account_id", "")).lower()
        account = self._w.accounts.get(wanted) or next(
            (a for a in self._w.accounts.values() if wanted in a["name"].lower()), None
        )
        if account is None:
            return ToolResult.failure(
                ErrorClass.NOT_FOUND, f"no account matching {args.get('account_id')!r}"
            )
        return ToolResult.success(account)

    def search_deals(self, args: Mapping[str, Any]) -> ToolResult:
        deals = list(self._w.deals)
        if args.get("account_id"):
            wanted = str(args["account_id"]).lower()
            deals = [d for d in deals if wanted in d["account_id"].lower() or wanted in d["name"].lower()]
        if args.get("stage"):
            deals = [d for d in deals if d["stage"] == args["stage"]]
        if args.get("owner"):
            deals = [d for d in deals if str(args["owner"]).lower() in d["owner"].lower()]
        return ToolResult.success({"deals": deals[: int(args.get("limit", 10))]})

    def log_activity(self, args: Mapping[str, Any]) -> ToolResult:
        record = {
            "activity_id": f"act-{len(self._w.activities) + 1:04d}",
            "deal_id": args.get("deal_id"),
            "kind": args.get("kind"),
            "summary": args.get("summary"),
            "outcome": args.get("outcome"),
            "logged_at": NOW,
        }
        self._w.activities.append(record)
        return ToolResult.success(record)

    def draft_email(self, args: Mapping[str, Any]) -> ToolResult:
        record = {
            "draft_id": f"draft-{len(self._w.drafts) + 1:04d}",
            "to": args.get("to"),
            "subject": args.get("subject"),
            "body": args.get("body"),
            "deal_id": args.get("deal_id"),
            "created_at": NOW,
        }
        self._w.drafts.append(record)
        return ToolResult.success(record)

    def send_email(self, args: Mapping[str, Any]) -> ToolResult:
        draft = next((d for d in self._w.drafts if d["draft_id"] == args.get("draft_id")), None)
        if draft is None:
            return ToolResult.failure(
                ErrorClass.NOT_FOUND, f"no draft {args.get('draft_id')!r}; draft before sending"
            )
        record = {
            "message_id": f"msg-{len(self._w.sent) + 1:04d}",
            "sent_at": NOW,
            "recipients": args.get("confirm_recipients", [draft["to"]]),
            "subject": draft["subject"],
        }
        self._w.sent.append({**record, "draft_id": draft["draft_id"]})
        return ToolResult.success(record)


class SupportMock:
    """Customer history, tickets, known issues, replies and refunds."""

    def __init__(self, w: World) -> None:
        self._w = w

    def invoke(self, method: str, args: dict[str, Any]) -> ToolResult:
        handler = getattr(self, method, None)
        if handler is None or method.startswith("_"):
            return ToolResult.failure(ErrorClass.UNKNOWN_TOOL, f"support has no method {method!r}")
        return handler(args)

    def get_customer(self, args: Mapping[str, Any]) -> ToolResult:
        wanted = str(args.get("customer_id", "")).lower()
        customer = self._w.customers.get(wanted) or next(
            (c for c in self._w.customers.values() if wanted in c["name"].lower()), None
        )
        if customer is None:
            return ToolResult.failure(
                ErrorClass.NOT_FOUND, f"no customer matching {args.get('customer_id')!r}"
            )
        return ToolResult.success(customer)

    def search_tickets(self, args: Mapping[str, Any]) -> ToolResult:
        tickets = list(self._w.tickets)
        if args.get("customer_id"):
            wanted = str(args["customer_id"]).lower()
            tickets = [t for t in tickets if wanted in t["customer_id"].lower()]
        if args.get("status"):
            tickets = [t for t in tickets if t["status"] == args["status"]]
        if args.get("query"):
            needle = str(args["query"]).lower()
            tickets = [
                t
                for t in tickets
                if needle in t["subject"].lower() or needle in t["resolution_note"].lower()
            ]
        return ToolResult.success({"tickets": tickets[: int(args.get("limit", 10))]})

    def get_known_issues(self, args: Mapping[str, Any]) -> ToolResult:
        issues = list(self._w.issues)
        if args.get("query"):
            needle = str(args["query"]).lower()
            matching = [
                i
                for i in issues
                if needle in i["title"].lower()
                or any(needle in s.lower() for s in i["symptoms"])
            ]
            # An empty match still returns the catalogue: a support agent diagnosing a symptom
            # needs to know which issues exist even when the query words do not line up.
            issues = matching or issues
        return ToolResult.success({"issues": issues})

    def draft_reply(self, args: Mapping[str, Any]) -> ToolResult:
        record = {
            "draft_id": f"rdraft-{len(self._w.drafts) + 1:04d}",
            "ticket_id": args.get("ticket_id"),
            "body": args.get("body"),
            "next_step": args.get("next_step"),
            "created_at": NOW,
        }
        self._w.drafts.append(record)
        return ToolResult.success(record)

    def send_reply(self, args: Mapping[str, Any]) -> ToolResult:
        draft = next((d for d in self._w.drafts if d["draft_id"] == args.get("draft_id")), None)
        if draft is None:
            return ToolResult.failure(
                ErrorClass.NOT_FOUND, f"no draft {args.get('draft_id')!r}; draft before sending"
            )
        record = {
            "message_id": f"smsg-{len(self._w.sent) + 1:04d}",
            "sent_at": NOW,
            "ticket_id": draft["ticket_id"],
        }
        self._w.sent.append({**record, "draft_id": draft["draft_id"]})
        return ToolResult.success(record)

    def issue_refund(self, args: Mapping[str, Any]) -> ToolResult:
        amount = float(args.get("amount_usd", 0))
        # The ceiling is a policy value, not a technical one: above it a human decides, which is
        # why this returns a classified failure rather than clamping the amount silently.
        if amount > REFUND_CEILING_USD:
            return ToolResult.failure(
                ErrorClass.PERMISSION,
                f"refund of {amount:.2f} USD exceeds the {REFUND_CEILING_USD:.0f} USD ceiling for "
                "automated credits; escalate for approval",
            )
        record = {
            "refund_id": f"rf-{len(self._w.refunds) + 1:04d}",
            "customer_id": args.get("customer_id"),
            "amount_usd": amount,
            "reason": args.get("reason"),
            "ticket_id": args.get("ticket_id"),
            "status": "processed",
            "processed_at": NOW,
        }
        self._w.refunds.append(record)
        return ToolResult.success(record)


def build(settings: dict[str, Any], *, root: Any = None, impl: str | None = None) -> Any:
    """Factory serving both business capabilities; ``settings["capability"]`` selects one."""
    capability = str(settings.get("capability", ""))
    if capability == "crm":
        return CrmMock(_WORLD)
    if capability == "support":
        return SupportMock(_WORLD)
    raise ValueError(f"brain.providers.mock.business cannot serve capability {capability!r}")
