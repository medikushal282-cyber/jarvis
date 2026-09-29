<!-- GENERATED FILE - DO NOT EDIT BY HAND.
     Regenerate with:  python -m brain.docs.gen_tools_md
     Source of truth:  config/tools/*.yaml
     A test asserts this file matches the registry, so editing it by hand will fail the build. -->

# Tool registry

Every tool the brain can call, generated from `config/tools/*.yaml`. A profile exposes a subset of
these by name; availability is a profile decision and permission is a tool decision, and both must
pass before a call leaves the loop.

## Summary

| Tool | Provider | Permission | Side effects | Idempotent | Timeout | Retries |
|---|---|---|---|---|---|---|

| `draft_email` | crm | **auto** | none | yes | 15s | 2 |
| `draft_reply` | support | **auto** | none | yes | 15s | 2 |
| `escalate_to_human` | incident | **auto** | mutating | yes | 15s | 2 |
| `fetch_metrics` | observability | **auto** | none | yes | 20s | 2 |
| `fetch_runbook` | incident | **auto** | none | yes | 10s | 3 |
| `get_account` | crm | **auto** | none | yes | 10s | 3 |
| `get_customer` | support | **auto** | none | yes | 10s | 3 |
| `get_known_issues` | support | **auto** | none | yes | 10s | 3 |
| `get_recent_deploys` | observability | **auto** | none | yes | 10s | 3 |
| `get_service_health` | observability | **auto** | none | yes | 10s | 3 |
| `inspect_runtime` | observability | **auto** | none | yes | 25s | 2 |
| `issue_refund` | support | **confirm** | destructive | no | 30s | 1 |
| `log_activity` | crm | **auto** | mutating | no | 10s | 2 |
| `open_ticket` | comms | **auto** | mutating | no | 15s | 3 |
| `page_oncall` | comms | **confirm** | mutating | no | 20s | 2 |
| `post_status_update` | comms | **confirm** | mutating | no | 15s | 3 |
| `recall_memory` | hindsight | **auto** | none | yes | 10s | 2 |
| `request_clarification` | incident | **auto** | none | yes | 5s | 1 |
| `restart_service` | remediation | **confirm** | destructive | no | 120s | 1 |
| `rollback_deploy` | remediation | **confirm** | destructive | no | 180s | 1 |
| `run_diagnostic_command` | remediation | **deny** | destructive | no | 60s | 1 |
| `save_memory` | hindsight | **auto** | mutating | no | 10s | 2 |
| `scale_replicas` | remediation | **confirm** | mutating | yes | 120s | 2 |
| `search_deals` | crm | **auto** | none | yes | 15s | 3 |
| `search_incident_history` | incident | **auto** | none | yes | 15s | 3 |
| `search_logs` | observability | **auto** | none | yes | 15s | 3 |
| `search_tickets` | support | **auto** | none | yes | 15s | 3 |
| `send_email` | crm | **confirm** | destructive | no | 30s | 1 |
| `send_reply` | support | **confirm** | destructive | no | 30s | 1 |

## Permission tiers

- **auto** -- runs unattended. Reads and memory operations only.
- **confirm** -- needs per-call human approval, with a quantified blast radius.
- **deny** -- never runs, at any autonomy level. A restriction to report, not to route around.

## Provider: `comms`

### `open_ticket`

Open a tracked ticket for follow-up work that is real but not part of resolving the current incident — a latent bug, a missing alert, a runbook that was wrong. Use it so that a finding is not lost when the incident closes. Do not use it in place of finishing the objective.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `body` | string | yes | - |
| `labels` | array | no | - |
| `links` | array | no | - |
| `severity` | string | no | one of `low`, `medium`, `high`; default `medium` |
| `title` | string | yes | - |

Returns: { ticket_id, url, title, created_at }

Retry: 3 attempt(s), exponential backoff, base 0.5s, jitter on, on timeout, rate_limited, provider_5xx.

### `page_oncall`

Page the human on-call engineer for this service. This interrupts someone, so use it only when the incident meets the paging threshold in the objective, or when escalate_to_human has already been chosen and the urgency warrants waking a person. For anything that can wait until business hours, open a ticket instead.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `message` | string | yes | - |
| `service` | string | yes | - |
| `urgency` | string | yes | one of `low`, `medium`, `high`, `critical` |

Returns: { page_id, notified: [ { name, channel, sent_at } ], acknowledged_by }

Redacts: `phone`, `email`

Retry: 2 attempt(s), fixed backoff, base 1s, jitter off, on timeout, provider_5xx.

### `post_status_update`

Publish an update to the service status page. Write for a customer reading it, not for an engineer: state impact, scope and what is being done, with no internal jargon and no speculation about cause until the cause is confirmed. Post once when the impact is understood and once when it is resolved; do not narrate your investigation in public.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `message` | string | yes | - |
| `service` | string | yes | - |
| `severity` | string | no | one of `minor`, `major`, `critical` |
| `status` | string | yes | one of `investigating`, `identified`, `monitoring`, `resolved` |

Returns: { update_id, service, status, published_at, url }

Retry: 3 attempt(s), exponential backoff, base 0.5s, jitter on, on timeout, rate_limited, provider_5xx.

## Provider: `crm`

### `draft_email`

Produce a draft message for a named recipient without sending it. Always prefer drafting first so a human can review tone and accuracy. The draft should be specific to this counterparty: reference what they actually raised, and do not reuse a generic template.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `body` | string | yes | - |
| `deal_id` | string | no | - |
| `subject` | string | yes | - |
| `to` | string | yes | - |

Returns: { draft_id, to, subject, body, created_at }

Retry: 2 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, provider_5xx.

### `get_account`

Load an account's profile: owner, segment, contract dates, products, and the stakeholders with their roles. Call this before drafting anything for an account, so the draft reflects who actually decides and who merely influences.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `account_id` | string | yes | - |

Returns: { id, name, segment, owner, arr_usd, renewal_date, products: [], stakeholders:
  [ { name, role, influence, last_contacted_at } ], health_score }

Redacts: `billing_contact_email`, `phone`

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `log_activity`

Record an interaction against a deal or account — a call, an email, a meeting — with its outcome. Log this whenever an interaction happened outside the agent, so the next run has an accurate picture.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `deal_id` | string | yes | - |
| `kind` | string | yes | one of `call`, `email`, `meeting`, `note` |
| `outcome` | string | no | one of `positive`, `neutral`, `negative`, `no_response` |
| `summary` | string | yes | - |

Returns: { activity_id, deal_id, logged_at }

Retry: 2 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, provider_5xx.

### `search_deals`

Search the pipeline for deals by account, stage or owner, returning stage, value, close date and the last recorded activity. Use it to ground a recommendation in the actual pipeline state instead of restating the request.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `account_id` | string | no | - |
| `limit` | integer | no | min 1; max 50; default `10` |
| `owner` | string | no | - |
| `stage` | string | no | one of `discovery`, `evaluation`, `proposal`, `negotiation`, `closed_won`, `closed_lost` |

Returns: { deals: [ { id, account_id, name, stage, amount_usd, close_date, owner,
             last_activity_at, competitors: [], objections: [] } ] }

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `send_email`

Send a previously drafted message to an external recipient. This is irreversible and leaves the organisation, so it is confirm-gated and should only be called after the draft has been shown. Never send to more recipients than the draft named.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `confirm_recipients` | array | yes | - |
| `draft_id` | string | yes | - |

Returns: { message_id, sent_at, recipients }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

## Provider: `hindsight`

### `recall_memory`

Search remembered experience for facts relevant to a specific question. Use this mid-plan when you need something the initial recall did not surface — a past resolution for a service, a stated operator preference, an entity fact such as an owner or an SLO. Ask a focused question and pass the entities involved; a vague query returns vague memories.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `entities` | array | no | - |
| `kinds` | array | no | - |
| `limit` | integer | no | min 1; max 20; default `5` |
| `query` | string | yes | - |

Returns: { memories: [ { id, kind, text, entities, confidence, observed_at, source_run_id,
                times_recalled, outcomes: { applied: int, succeeded: int } } ] }

Retry: 2 attempt(s), exponential backoff, base 0.3s, jitter on, on timeout, rate_limited, provider_5xx.

### `save_memory`

Record something worth carrying into future runs, before this run ends. Save an operator correction or preference, a fact about an entity that took effort to establish, or a resolution that worked. Write it as a standalone statement that will still make sense weeks later with no surrounding context: name the entities explicitly, and say what happened and what it implies. Do not save narration of this run, restatements of the objective, or anything already in the incident record — the RETAIN state handles the ordinary case automatically.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `confidence` | number | no | min 0; max 1; default `0.7` |
| `entities` | array | no | - |
| `kind` | string | yes | one of `outcome`, `failure`, `correction`, `preference`, `entity_fact` |
| `text` | string | yes | - |

Returns: { memory_id, stored: bool, deduplicated_with }

Retry: 2 attempt(s), exponential backoff, base 0.3s, jitter on, on timeout, rate_limited, provider_5xx.

## Provider: `incident`

### `escalate_to_human`

Hand the incident to a human on-call engineer with a written handover. Use this when you have exhausted safe automated options, when the remaining fix is destructive beyond your authority, or when the blast radius is larger than the objective allows. The handover must include what you ruled out and what you would try next, so the human does not repeat your work.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `reason` | string | yes | - |
| `ruled_out` | array | no | - |
| `suggested_next` | string | no | - |
| `summary` | string | yes | - |
| `urgency` | string | no | one of `low`, `medium`, `high`, `critical`; default `medium` |

Returns: { handover_id, paged: [ { name, role, channel } ], acknowledged_by }

Retry: 2 attempt(s), fixed backoff, base 1s, jitter off, on timeout, provider_5xx.

### `fetch_runbook`

Retrieve the operational runbook matching a symptom or service. Call this before choosing a remediation: the runbook states the ordered checks the team has agreed on and the actions that require a human. If it returns several candidates, prefer the one whose `trigger` best matches the observed signature.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `service` | string | no | - |
| `symptom` | string | yes | - |

Returns: { runbooks: [ { id, title, trigger, service, steps: [ { order, action, tool_hint,
                requires_approval } ], last_reviewed, owner } ] }

Retry: 3 attempt(s), exponential backoff, base 0.3s, jitter on, on timeout, rate_limited, provider_5xx.

### `request_clarification`

Ask the operator a question and stop until they answer. Use this when the objective is genuinely ambiguous, when two remediations are equally plausible and the choice is not yours to make, or when a needed input (an approval, an identifier, a business decision) can only come from a person. State exactly what you need and why, and offer the options you are choosing between. Do not use this to ask permission for something a policy already pre-approves — that is what the confirm tier is for.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `options` | array | no | - |
| `question` | string | yes | - |
| `why_blocked` | string | yes | - |

Returns: { answer: string, answered_by: string, answered_at: iso8601 }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

### `search_incident_history`

Search the incident record for past incidents matching a service, symptom or error signature, and return how each was actually resolved. This is the structured operational record, distinct from remembered experience: it returns authoritative post-incident data, including the fix that worked and the one that made things worse.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `limit` | integer | no | min 1; max 50; default `10` |
| `query` | string | yes | - |
| `service` | string | no | - |

Returns: { incidents: [ { id, service, title, opened_at, resolved_at, duration_minutes,
                 severity, root_cause, resolution_steps, resolution_worked: bool,
                 what_failed, postmortem_url } ] }

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

## Provider: `observability`

### `fetch_metrics`

Query a numeric time series for one service and metric over a window. Use this to confirm a hypothesis quantitatively — a saturation curve, a step change at a deploy boundary, a memory sawtooth — rather than inferring it from log text alone.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `metric` | string | yes | one of `cpu_utilization_pct`, `memory_used_pct`, `request_rate_rps`, `error_rate_pct`, `latency_p95_ms`, `db_pool_active`, `db_pool_max`, `gc_pause_ms`, `queue_depth` |
| `service` | string | yes | - |
| `step_seconds` | integer | no | min 10; max 3600; default `60` |
| `window_minutes` | integer | no | min 5; max 4320; default `60` |

Returns: { service, metric, unit, points: [ { ts, value } ], summary: { min, max, mean, last } }

Retry: 2 attempt(s), exponential backoff, base 0.5s, jitter on, on timeout, rate_limited, provider_5xx.

### `get_recent_deploys`

Deployment history for a service: who shipped what, when, and whether it was rolled back. Call this early whenever a symptom has a sharp onset — a change boundary is the single most common cause, and correlating onset with the nearest deploy is cheaper than bisecting.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `limit` | integer | no | min 1; max 100; default `20` |
| `service` | string | yes | - |
| `window_hours` | integer | no | min 1; max 720; default `72` |

Returns: { deploys: [ { id, service, version, commit, author, deployed_at, status,
               rolled_back, change_summary, files_touched } ] }

Redacts: `author_email`

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `get_service_health`

Current health snapshot for one service or for every service. This is the tool to call first when a symptom is vague, and again after a remediation to verify the service actually recovered. Returns status, error rate, latency percentiles, replica counts and the SLO burn rate.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `service` | string | no | - |

Returns: { services: [ { service, status, error_rate_pct, p50_ms, p95_ms, p99_ms,
                replicas_desired, replicas_ready, slo_burn_rate, since } ] }

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `inspect_runtime`

Read process-level state for a service: open connections, thread or worker counts, blocked-thread stacks, connection-pool waiters. This is the deeper look you take when a health snapshot says the service is degraded but logs alone do not explain why.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `include` | array | no | - |
| `replica` | string | no | - |
| `service` | string | yes | - |

Returns: { replica, sections: { connections, pool_stats, threads, gc_stats, config } }

Redacts: `config.env`, `config.secrets`, `connection_strings`

Retry: 2 attempt(s), exponential backoff, base 0.5s, jitter on, on timeout, provider_5xx.

### `search_logs`

Search application logs for one service inside a time window. Use this to find the concrete error signature, stack frames and first-occurrence timestamp behind a symptom. Prefer a narrow `query` and a short window over pulling everything.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `limit` | integer | no | min 1; max 500; default `100` |
| `min_level` | string | no | one of `debug`, `info`, `warn`, `error`, `fatal`; default `warn` |
| `query` | string | no | - |
| `service` | string | yes | - |
| `window_minutes` | integer | no | min 1; max 1440; default `60` |

Returns: { entries: [ { ts, level, service, message, trace_id, fields } ], truncated: bool }

Redacts: `env`, `tokens`, `authorization`

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

## Provider: `remediation`

### `restart_service`

Perform a rolling restart of a service's replicas. This sheds in-flight requests on each replica as it cycles, so it is disruptive: use it only when a stateless process is wedged (leaked threads, stuck workers) and a deploy boundary is not implicated. If the symptom started at a deploy, roll back instead — a restart will not undo a bad release and will hide the evidence. Prefer the smallest replica count that restores health, and verify with get_service_health afterwards.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `dry_run` | boolean | no | default `False` |
| `reason` | string | yes | - |
| `replicas` | string | no | one of `one`, `half`, `all`; default `one` |
| `service` | string | yes | - |

Returns: { action_id, service, replicas_cycled, started_at, completed_at, resulting_status,
  requests_dropped_estimate }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

### `rollback_deploy`

Roll a service back to a previous known-good version. This is the correct first response when a symptom's onset lines up with a deploy boundary — it directly undoes the suspected change instead of masking it. Requires the target deploy id; take it from get_recent_deploys. Rolling back a database migration is not covered by this tool and must be escalated.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `dry_run` | boolean | no | default `False` |
| `reason` | string | yes | - |
| `service` | string | yes | - |
| `to_deploy_id` | string | yes | - |

Returns: { action_id, service, from_version, to_version, started_at, completed_at,
  resulting_status, schema_compatible: bool }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

### `run_diagnostic_command`

Execute an arbitrary shell command against a service host. This is deliberately denied by default: it would let a compromised or confused plan bypass every other guard in this file, and it is not needed for the incident workflow, which has specific tools for every read it performs. It exists in the registry so the policy engine has something real to refuse, and so an operator who genuinely needs it can lift it deliberately for one run rather than discovering there is no such lever.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `command` | string | yes | - |
| `service` | string | yes | - |

Returns: { stdout, stderr, exit_code }

Redacts: `stdout`, `stderr`

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

### `scale_replicas`

Change the desired replica count for a service. Adding capacity relieves load-driven saturation (queue depth, CPU, pool wait) but only masks a leak — if memory or connections climb monotonically, scaling buys time and does not fix the cause, and you should say so rather than presenting it as a resolution. Scaling down is disruptive and is treated with the same care as a restart.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `dry_run` | boolean | no | default `False` |
| `reason` | string | yes | - |
| `replicas` | integer | yes | min 1; max 200 |
| `service` | string | yes | - |

Returns: { action_id, service, replicas_before, replicas_after, started_at, completed_at,
  resulting_status }

Retry: 2 attempt(s), exponential backoff, base 1s, jitter on, on timeout, provider_5xx.

## Provider: `support`

### `draft_reply`

Produce a customer-facing reply draft without sending it. Match the customer's demonstrated expertise: do not explain fundamentals to an engineer, and do not assume fluency with a non-technical requester. Lead with the answer or the workaround, and state plainly what is not yet known.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `body` | string | yes | - |
| `next_step` | string | no | - |
| `ticket_id` | string | yes | - |

Returns: { draft_id, ticket_id, body, created_at }

Retry: 2 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, provider_5xx.

### `get_customer`

Load a customer's profile: plan, tenure, entitlements, environment and open tickets. Call this before responding to any support request so the answer respects their entitlement and their history rather than treating the request in isolation.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `customer_id` | string | yes | - |

Returns: { id, name, plan, tenure_months, entitlements: [], environment,
  open_tickets: [ { id, subject, opened_at, status } ], sentiment_trend, csm }

Redacts: `contact_email`, `phone`

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `get_known_issues`

List currently known issues with their workarounds and fix status. Check this before proposing a novel explanation: if the symptom matches a known issue, the honest answer is the known issue and its workaround, not a fresh diagnosis.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `include_fixed` | boolean | no | default `False` |
| `query` | string | no | - |

Returns: { issues: [ { id, title, symptoms, affected_versions, workaround, fix_version,
              status, updated_at } ] }

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `issue_refund`

Issue a refund or credit against a customer's account. This moves money and is irreversible, so it is confirm-gated and capped by policy. Always state the amount and the reason in the confirmation, and never exceed the entitlement the customer's plan allows.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `amount_usd` | number | yes | min 0; max 5000 |
| `customer_id` | string | yes | - |
| `reason` | string | yes | - |
| `ticket_id` | string | no | - |

Returns: { refund_id, customer_id, amount_usd, status, processed_at }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

### `search_tickets`

Search tickets by customer, status, tag or free text, with resolution notes where closed. Use it to check whether this has happened before and how it was handled.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `customer_id` | string | no | - |
| `limit` | integer | no | min 1; max 50; default `10` |
| `query` | string | no | - |
| `status` | string | no | one of `open`, `pending`, `resolved`, `closed` |

Returns: { tickets: [ { id, customer_id, subject, status, priority, opened_at, resolved_at,
               tags: [], resolution_note, reopened_count } ] }

Retry: 3 attempt(s), exponential backoff, base 0.4s, jitter on, on timeout, rate_limited, provider_5xx.

### `send_reply`

Send a drafted reply to the customer. Irreversible and customer-visible, so it is confirm-gated. Escalating tone or a frustrated customer is a reason to prefer a human review over this tool.

| Argument | Type | Required | Constraints |
|---|---|---|---|
| `confirm_ticket` | string | yes | - |
| `draft_id` | string | yes | - |

Returns: { message_id, sent_at, ticket_id }

Retry: 1 attempt(s), fixed backoff, base 0s, jitter off, on nothing.

