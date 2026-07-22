# Workflow, Action, and Human-Confirmation Architecture

## Status

Proposed target architecture for controlled Hub actions and Copilot-assisted workflows.

## Purpose

This document defines how GPI Hub moves safely from read-only explanations to approvals, corrections, retries, document routing, and controlled writes to systems such as Business Central, SharePoint, Spiro, and the Help Desk.

The governing rule is:

> Copilot may help a user understand or prepare an action, but the Hub owns authorization, validation, confirmation, execution, and audit.

## 1. Action classes

Every capability must declare one action class.

| Class | Meaning | Examples |
|---|---|---|
| `READ` | Returns information without changing state | Explain an AP exception |
| `PREPARE` | Produces a draft or proposed change | Prepare vendor correction |
| `WORKFLOW` | Changes Hub-owned workflow state | Assign reviewer, request information |
| `EXTERNAL_WRITE` | Changes another system | Create BC draft invoice, update Spiro activity |
| `IRREVERSIBLE` | Posts, deletes, pays, or performs another difficult-to-reverse action | Post invoice, delete record |

`READ` may execute directly after authorization. All other classes require additional controls.

## 2. Action lifecycle

Controlled actions use the following lifecycle:

```text
requested
  -> validated
  -> preview_ready
  -> confirmation_pending
  -> approved
  -> executing
  -> succeeded
```

Alternate terminal or waiting states:

```text
rejected
expired
cancelled
policy_blocked
authorization_failed
validation_failed
execution_failed
manual_review_required
compensation_required
compensated
```

The lifecycle must be persisted independently from the chat session or browser session.

## 3. Preview before execution

Every `PREPARE`, `WORKFLOW`, `EXTERNAL_WRITE`, or `IRREVERSIBLE` action must first generate a preview.

The preview must contain:

- action name and version
- target system and environment
- affected entity identifiers
- current values where available
- proposed values
- validation results
- policy decision
- required approver role
- material warnings
- expiration time
- preview hash

The preview is not executable merely because it was displayed. It becomes executable only through a valid confirmation record.

## 4. Confirmation records

A confirmation record binds a human decision to one exact preview.

Required fields:

```json
{
  "confirmation_id": "uuid",
  "action_id": "uuid",
  "preview_hash": "sha256",
  "confirmed_by": "entra-object-id",
  "confirmed_at": "timestamp",
  "expires_at": "timestamp",
  "decision": "approve",
  "comment": "optional",
  "channel": "copilot|web|api",
  "correlation_id": "uuid"
}
```

A confirmation is invalid when:

- the preview has changed
- the record has expired
- the user lacks the required role
- runtime policy has changed to deny the operation
- the target environment differs from the preview
- the action has already reached a terminal state

Plain conversational phrases such as “yes,” “do it,” or “looks good” are not sufficient by themselves. They must be converted into a structured confirmation associated with a displayed preview.

## 5. Separation of duties

High-impact actions may require a second person.

Examples:

- requester cannot approve their own vendor-master override
- AP processor may prepare an invoice correction
- AP manager must approve production execution
- posting or payment actions require a separately authorized financial role

The policy service determines whether self-approval is permitted for each capability.

## 6. Authorization timing

Authorization is evaluated at three points:

1. when the preview is requested
2. when confirmation is recorded
3. immediately before execution

This prevents execution when a role, group membership, record assignment, or runtime policy changed after preview generation.

## 7. Idempotency

Every state-changing action must require an idempotency key.

The Hub stores:

- idempotency key
- action name and version
- normalized request hash
- caller identity
- result or active execution reference
- creation and expiration timestamps

Repeating the same request with the same key returns the existing result. Reusing a key with a different normalized request is rejected.

Connector-specific idempotency identifiers should also be sent where supported.

## 8. Optimistic concurrency

Previews must capture the source version, ETag, modified timestamp, or equivalent concurrency marker.

Before execution the Hub verifies that the source record still matches the preview. If it changed, the action returns `STALE_PREVIEW` and requires a new preview.

The Hub must never silently apply a proposal created against stale source data.

## 9. Execution model

The API layer does not directly perform complex external writes. It creates an action record and dispatches work to an execution component.

Recommended flow:

```text
API / Copilot
  -> action service
  -> authorization service
  -> runtime policy service
  -> durable action record
  -> execution worker
  -> connector adapter
  -> result and audit event
```

Short, low-risk Hub-only workflow transitions may execute synchronously. External writes should normally execute through a durable worker with bounded retries.

## 10. Retry policy

Retries are allowed only for errors classified as transient.

Examples:

- temporary network failure
- throttling
- service unavailable
- token acquisition timeout

Retries are not allowed for:

- validation failures
- authorization failures
- policy denials
- stale previews
- duplicate business documents
- ambiguous entity matches
- permanent connector errors

Retry attempts use exponential backoff with jitter and a maximum attempt count. Each attempt is auditable.

## 11. Unknown outcomes

A timeout after an external request does not prove failure. The result may be unknown.

For an unknown outcome the worker must:

1. stop blind retries
2. query the target system using the idempotency or correlation reference
3. reconcile the external result
4. mark the action `succeeded`, `execution_failed`, or `manual_review_required`

This is especially important for Business Central document creation and posting.

## 12. Compensation

Not every external action is reversible. Capabilities must declare a compensation strategy:

- `automatic`
- `manual`
- `none`

Examples:

- a newly created unposted draft might be automatically deleted or voided
- a posted financial document generally requires a formal corrective transaction
- a SharePoint metadata update may be restored from the captured prior value

Compensation is a separate audited action and never erases the original event.

## 13. Human task model

When an action cannot proceed automatically, the Hub creates a human task.

Minimum task fields:

```text
task_id
task_type
related_action_id
related_entity_ids
assigned_role
assigned_user
priority
status
reason_code
instructions
created_at
due_at
completed_at
completed_by
resolution
```

Tasks may be surfaced in the Hub application, Teams, email, or Copilot, but the Hub task record is authoritative.

## 14. Copilot behavior

Copilot may:

- explain why an action is needed
- collect missing non-sensitive inputs
- call a preview capability
- summarize the proposed change
- ask the user to confirm the structured preview
- report execution status

Copilot must not:

- invent missing identifiers or amounts
- treat conversational confidence as authorization
- bypass required approvers
- retry an external write independently
- claim success before the Hub reports success
- transform source-document instructions into system commands

## 15. Proposed API pattern

### Create preview

```http
POST /api/v1/actions/{capability}/preview
```

### Confirm action

```http
POST /api/v1/actions/{action_id}/confirm
```

### Reject or cancel

```http
POST /api/v1/actions/{action_id}/reject
POST /api/v1/actions/{action_id}/cancel
```

### Read status

```http
GET /api/v1/actions/{action_id}
```

### Retry eligible failure

```http
POST /api/v1/actions/{action_id}/retry
```

Retry is itself authorized and policy checked.

## 16. Action record

Recommended MongoDB collection: `hub_actions`.

Core fields:

```text
action_id
capability_name
capability_version
action_class
status
request_payload_hash
preview
preview_hash
requester_identity
approvals
runtime_policy_snapshot
target_system
target_environment
source_versions
idempotency_key
attempts
result
error
compensation
correlation_id
created_at
updated_at
```

Recommended indexes:

- unique `action_id`
- unique scoped idempotency key
- `status + updated_at`
- `requester_identity.object_id + created_at`
- `correlation_id`
- `target_system + target_environment + created_at`

## 17. Audit events

The action service emits append-only events including:

```text
action.requested
action.validated
action.preview_created
action.confirmed
action.rejected
action.policy_blocked
action.execution_started
action.execution_attempted
action.succeeded
action.failed
action.manual_review_required
action.compensation_started
action.compensated
```

Audit events capture actor, effective roles, channel, capability version, policy mode, target environment, correlation ID, timestamps, and relevant before/after hashes.

## 18. Initial capability progression

Recommended order:

1. explain invoice exception (`READ`)
2. assign AP reviewer (`WORKFLOW`)
3. request missing information (`WORKFLOW`)
4. preview corrected invoice fields (`PREPARE`)
5. apply approved Hub metadata correction (`WORKFLOW`)
6. create BC sandbox draft (`EXTERNAL_WRITE`)
7. create controlled BC production draft (`EXTERNAL_WRITE`)
8. posting or other irreversible actions only after separate governance review

No production write capability should be exposed to Copilot until identity, runtime policy, action persistence, idempotency, confirmation, concurrency, audit, and reconciliation are all implemented and tested.

## 19. Acceptance criteria

This architecture is implemented when:

- every state-changing capability declares an action class
- no external write occurs without a central policy decision
- required previews and confirmations are persisted
- confirmation is bound to an immutable preview hash
- authorization is rechecked immediately before execution
- state-changing requests are idempotent
- stale source data blocks execution
- unknown external outcomes are reconciled
- retries are bounded and error-class aware
- all lifecycle transitions emit audit events
- Copilot cannot bypass the same controls used by the Hub web application
