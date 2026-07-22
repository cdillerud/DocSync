# GPI Hub Identity and Role Model

**Status:** Draft  
**Applies to:** Hub UI, API clients, background services, Copilot Studio, future agents

## 1. Purpose

This document defines how GPI Hub identifies users and applications, maps Microsoft Entra identities to Hub roles, and enforces authorization consistently across all routes and capabilities.

The Hub must never trust a username, email address, or role supplied in request content. Identity must come from a validated Entra token or a controlled service identity.

## 2. Identity Authorities

### Human users

Microsoft Entra ID is the identity authority for all employee-driven requests.

Required token validation:

- Signature
- Issuer
- Tenant ID
- Audience
- Expiration
- Not-before time
- Object ID
- Token type

### Service identities

Background jobs and integrations must use dedicated managed identities or app registrations.

Examples:

- AP mailbox polling
- Sales mailbox polling
- SharePoint synchronization
- Business Central cache refresh
- Scheduled summaries
- Copilot Studio connector identity

A service identity must never be represented as a human user.

## 3. Request Identity Context

Every protected request must create one immutable identity context.

```python
class IdentityContext(BaseModel):
    subject_type: Literal["user", "service"]
    tenant_id: str
    object_id: str
    display_name: str | None = None
    email: str | None = None
    app_id: str | None = None
    token_roles: list[str] = []
    group_ids: list[str] = []
    hub_roles: list[str] = []
    correlation_id: str
    authentication_method: str
```

This context must be passed into capability and action services. Domain services may not reconstruct identity from raw headers.

## 4. Role Model

Hub roles describe business permission, not job title.

Initial roles:

| Role | Purpose |
|---|---|
| `hub.reader` | Basic authenticated access to non-sensitive Hub information |
| `hub.documents.reader` | View documents allowed by record-level policy |
| `hub.ap.reader` | View AP invoices and AP workflow state |
| `hub.ap.reviewer` | Resolve AP exceptions and submit review decisions |
| `hub.ap.approver` | Approve eligible AP transactions |
| `hub.sales.reader` | View sales orders, customers, and sales documents |
| `hub.sales.manager` | View team-level sales context and manager reports |
| `hub.bc.draft_creator` | Create approved BC drafts in allowed environments |
| `hub.bc.production_writer` | Execute specifically approved production capabilities |
| `hub.it.support` | Access IT support, user, and device capabilities |
| `hub.audit.reader` | View security and capability audit events |
| `hub.administrator` | Configure Hub policy and role mappings |

Possession of a broad role does not automatically grant every action. Each capability still defines required roles and runtime policy.

## 5. Entra Mapping

Preferred mapping order:

1. Entra application roles for stable application permissions.
2. Entra security groups mapped to Hub roles.
3. Temporary explicit assignments only for controlled pilot use.

Example configuration:

```json
{
  "group_role_mappings": {
    "<entra-group-object-id>": ["hub.ap.reader", "hub.ap.reviewer"],
    "<entra-group-object-id-2>": ["hub.sales.reader", "hub.sales.manager"]
  }
}
```

Mappings must use immutable Entra object IDs, not display names.

## 6. Group Overages

Entra tokens may omit full group membership when a user belongs to many groups.

The identity layer must support:

- Direct `groups` claims when present.
- Microsoft Graph group resolution when an overage claim is present.
- Short-lived caching of resolved group IDs.
- Fail-closed behavior if required group resolution fails.

## 7. Authorization Layers

Every request is evaluated in this order:

1. Authentication
2. Tenant validation
3. Capability permission
4. Runtime-policy permission
5. Record-level permission
6. Field-level filtering
7. Action validation and confirmation, when applicable

### Capability authorization

```python
require_capability(
    identity=context,
    capability="explain_invoice_exception",
    required_roles={"hub.ap.reader"},
)
```

### Record-level authorization

Examples:

- Sales representatives may see assigned customers only.
- Sales managers may see their team.
- AP users may see AP records but not HR documents.
- IT support users may see device information but not financial records.
- Executives may receive aggregate results without unrestricted raw-document access.

## 8. Copilot Studio Identity

Preferred pattern:

```text
User signs into Microsoft 365
        ↓
Copilot Studio invokes Hub action
        ↓
Delegated user token reaches Hub
        ↓
Hub validates token and authorizes user
```

Where delegated identity cannot be used, the connector may authenticate as an application only if the request also carries a verifiable user assertion issued by a trusted Microsoft component.

The Hub must reject ordinary request fields such as:

```json
{"user_email": "someone@gamerpackaging.com"}
```

as proof of identity.

## 9. Background Jobs

Background jobs use service identities and explicit capability allowlists.

Example:

```json
{
  "service_identity": "hub-ap-mail-poller",
  "allowed_capabilities": [
    "ingest_ap_email",
    "classify_document",
    "store_document"
  ]
}
```

A polling identity must not automatically gain posting or approval permissions.

## 10. Break-Glass Administration

A break-glass role may exist only with:

- Separate Entra account
- Strong MFA
- Conditional Access
- No daily-use mailbox
- Explicit alerting
- Full audit capture
- Periodic access review

No local `admin/admin` fallback is permitted outside isolated development tests.

## 11. Audit Requirements

Every protected request records:

- Entra object ID or service principal ID
- Effective Hub roles
- Capability
- Authorization decision
- Record filter applied
- Source systems accessed
- Outcome
- Correlation ID

Denied requests must also be audited without recording sensitive response data.

## 12. Migration Plan

1. Add Entra JWT validation alongside current demo authentication in development only.
2. Add `IdentityContext` dependency.
3. Protect `/api/v1` first.
4. Add role mapping configuration.
5. Protect existing legacy routes.
6. Remove duplicate test auth from `server.py`, `server_new.py`, and `routes/auth.py`.
7. Remove default JWT secrets and local administrator credentials.
8. Require Entra authentication in all non-development modes.

## 13. Release Gates

No Copilot capability may enter pilot until:

- Token validation is tested.
- Tenant and audience restrictions are enforced.
- Roles are mapped by immutable IDs.
- Denied requests are audited.
- Record-level filtering is tested.
- No caller-supplied identity field is trusted.
