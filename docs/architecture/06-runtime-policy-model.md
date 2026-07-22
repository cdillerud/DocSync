# GPI Hub Runtime Policy Model

**Status:** Draft  
**Purpose:** Replace overlapping feature flags with one centralized, fail-closed execution policy.

## 1. Problem

The current Hub uses several independent flags to control behavior, including demo mode, pilot mode, Business Central mock mode, auto-posting, writeback, draft creation, and sales-order creation.

These flags are useful individually but can create ambiguous combinations. A capability should not determine safety by checking whichever flags happen to be visible in its module.

The Hub requires one runtime policy decision for every external operation.

## 2. Operating Modes

Exactly one operating mode is active per deployed Hub instance.

```python
class OperatingMode(str, Enum):
    DEVELOPMENT = "development"
    SHADOW = "shadow"
    PILOT_READ_ONLY = "pilot_read_only"
    SANDBOX_ACTIONS = "sandbox_actions"
    PRODUCTION_READ_ONLY = "production_read_only"
    CONTROLLED_PRODUCTION_ACTIONS = "controlled_production_actions"
```

### DEVELOPMENT

- Mock data and local development permitted.
- No production credentials.
- No external production writes.
- Demo authentication may exist only in an isolated developer configuration.

### SHADOW

- Live ingestion and observation may run.
- Source-system reads may be allowed.
- External writes are denied.
- Proposed actions may be simulated and audited.

### PILOT_READ_ONLY

- Authenticated pilot users may use approved knowledge capabilities.
- Production reads are permitted by capability policy.
- All mutations are denied.

### SANDBOX_ACTIONS

- Approved read and action capabilities may target sandbox systems.
- Production mutations are denied.
- Preview, confirmation, idempotency, and audit are required for actions.

### PRODUCTION_READ_ONLY

- Broad approved production retrieval is available.
- No production mutations.
- Sandbox actions may remain available if explicitly configured.

### CONTROLLED_PRODUCTION_ACTIONS

- Only explicitly approved production action capabilities are enabled.
- Preview, confirmation, idempotency, authorization, and post-execution verification are mandatory.
- A global emergency write-disable switch remains available.

## 3. Operation Classification

Every connector operation must be classified.

```python
class OperationClass(str, Enum):
    LOCAL_READ = "local_read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_READ = "external_read"
    EXTERNAL_WRITE = "external_write"
    FINANCIAL_MUTATION = "financial_mutation"
    IDENTITY_MUTATION = "identity_mutation"
    COMMUNICATION_SEND = "communication_send"
```

Every target must also be classified:

```python
class TargetEnvironment(str, Enum):
    LOCAL = "local"
    SANDBOX = "sandbox"
    PRODUCTION = "production"
```

## 4. Capability Policy

Each capability declares its maximum authority.

```json
{
  "name": "explain_invoice_exception",
  "class": "knowledge",
  "allowed_modes": [
    "pilot_read_only",
    "sandbox_actions",
    "production_read_only",
    "controlled_production_actions"
  ],
  "operations": [
    {
      "system": "business_central",
      "operation_class": "external_read",
      "allowed_environments": ["production"]
    }
  ],
  "confirmation_required": false
}
```

Action example:

```json
{
  "name": "create_purchase_invoice_draft",
  "class": "action",
  "allowed_modes": ["sandbox_actions", "controlled_production_actions"],
  "operations": [
    {
      "system": "business_central",
      "operation_class": "financial_mutation",
      "allowed_environments": ["sandbox"]
    }
  ],
  "confirmation_required": true,
  "idempotency_required": true
}
```

Production must never be inferred from a URL or credential. It must be explicitly declared and authorized.

## 5. Central Decision Function

All external operations call one policy service.

```python
class PolicyDecision(BaseModel):
    allowed: bool
    reason_code: str
    operating_mode: OperatingMode
    capability: str
    operation_class: OperationClass
    target_system: str
    target_environment: TargetEnvironment
    confirmation_required: bool
    audit_level: str


def authorize_operation(
    *,
    identity: IdentityContext,
    capability: CapabilityDefinition,
    operation_class: OperationClass,
    target_system: str,
    target_environment: TargetEnvironment,
) -> PolicyDecision:
    ...
```

Connectors must receive an allowed `PolicyDecision` before executing. They may not evaluate raw environment flags independently.

## 6. Fail-Closed Startup Validation

The application must refuse startup when configuration contradicts the operating mode.

Examples:

- Development mode with production credentials mounted.
- Pilot read-only mode with auto-post enabled.
- Production read-only mode with production write capability enabled.
- Sandbox-actions mode whose BC write adapter points to Production.
- Controlled-production-actions mode without audit persistence.
- Any non-development mode with demo authentication enabled.

Example configuration object:

```python
class RuntimeSettings(BaseSettings):
    operating_mode: OperatingMode
    emergency_external_write_disable: bool = True
    demo_auth_enabled: bool = False
    audit_enabled: bool = True
    bc_read_environment: TargetEnvironment
    bc_write_environment: TargetEnvironment | None = None
```

## 7. Emergency Write Disable

One global emergency control must deny all external mutations without disabling read-only operations.

```text
EMERGENCY_EXTERNAL_WRITE_DISABLE=true
```

Requirements:

- Defaults to `true` in new environments.
- Evaluated centrally.
- Cannot be overridden by a capability.
- Produces a high-severity audit event when it blocks an attempted action.
- Changes require authorized administration and are themselves audited.

## 8. Business Central Adapters

Use distinct adapters:

```text
BusinessCentralProductionReadClient
BusinessCentralSandboxReadClient
BusinessCentralSandboxWriteClient
BusinessCentralProductionWriteClient
```

The production-write client should not be registered in the application container unless the operating mode is `CONTROLLED_PRODUCTION_ACTIONS`.

A read client must not expose mutation methods.

## 9. Background Processes

Background jobs are subject to the same policy service.

Examples:

- Email polling: external read + local write.
- SharePoint upload: external write.
- BC cache refresh: external read + local write.
- Auto-post: financial mutation.
- Daily summary email: communication send.

No background job is exempt merely because it has no interactive user.

## 10. Copilot and Agent Controls

Copilot Studio may invoke only capabilities listed in the capability registry for the current mode.

The Hub must not expose a production mutation in the OpenAPI action set when policy denies it. Runtime enforcement remains mandatory even when a tool is hidden.

A conversational instruction such as “ignore the pilot restriction” has no effect on policy evaluation.

## 11. Audit Events

Every policy decision records:

- Operating mode
- Capability
- Subject identity
- Operation class
- Target system
- Target environment
- Allowed or denied
- Reason code
- Confirmation requirement
- Correlation ID

Recommended reason codes:

```text
POLICY_ALLOWED
MODE_NOT_ALLOWED
TARGET_ENVIRONMENT_NOT_ALLOWED
ROLE_NOT_ALLOWED
EMERGENCY_WRITE_DISABLED
CONFIRMATION_REQUIRED
SERVICE_IDENTITY_NOT_ALLOWED
AUDIT_UNAVAILABLE
CONFIGURATION_INVALID
```

## 12. Migration from Existing Flags

Existing flags should be mapped temporarily, then deprecated.

| Existing flag | Replacement |
|---|---|
| `DEMO_MODE` | `OperatingMode.DEVELOPMENT` plus connector configuration |
| `PILOT_MODE_ENABLED` | `SHADOW` or `PILOT_READ_ONLY` |
| `BC_MOCK_MODE` | Connector selection in development |
| `AUTO_POST_ENABLED` | Capability definition plus runtime policy |
| `BC_WRITEBACK_LINK_ENABLED` | Capability definition plus target policy |
| `ENABLE_CREATE_DRAFT_HEADER` | Draft capability registration |
| `AUTO_CREATE_SALES_ORDER_ENABLED` | Sales-order capability registration |

During migration, legacy flags may be read only by a compatibility adapter. Domain services should stop reading them directly.

## 13. Implementation Sequence

1. Add operating-mode and operation-class enums.
2. Add validated runtime settings.
3. Add startup contradiction checks.
4. Add policy decision service.
5. Wrap Business Central calls first.
6. Wrap SharePoint and Graph writes.
7. Apply policy to background jobs.
8. Apply policy to legacy routes.
9. Remove direct feature-flag checks from domain services.
10. Deprecate and remove compatibility mappings.

## 14. Release Gates

Before the first Copilot pilot:

- The deployed mode is explicit and visible in health/status output.
- Production write adapters are absent.
- Emergency write disable is enabled.
- All Copilot-exposed connector calls use central policy.
- Contradictory configurations fail startup tests.
- Policy denials are audited.

Before any production action:

- The capability is explicitly approved.
- Production write adapter registration is reviewed.
- Confirmation and idempotency are enforced.
- Audit storage is healthy.
- Reconciliation and rollback procedures exist.
