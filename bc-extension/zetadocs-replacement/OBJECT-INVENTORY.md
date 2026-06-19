# GPI Extension Object Inventory

## Object ranges

- Phase 1: 70510..70549
- Phase 2: 70550..70649

New Phase 2 objects must not reuse Phase 1 IDs.

## Assigned Phase 2 objects

| Object type | ID | Name | Purpose |
|---|---:|---|---|
| Codeunit | 70550 | GPI Phase 2 Email Mgt. | Current-user sender account resolution and recipient normalization |
| Permission Set Extension | 70550 | GPI PH2 DOC EMAIL | Adds Phase 2 service permissions to GPI DOC EMAIL |
| Codeunit | 70551 | GPI Sales Return Email | Sales Return Authorization and warehouse notification email workflows |
| Report | 70551 | GPI Sales Return Auth. | Customer-facing Sales Return Authorization |
| Report | 70552 | GPI Sales Return WH Notice | Warehouse-facing Sales Return Notification |
| Page Extension | 70551 | GPI Sales Return Documents | Sales Return Order email, preview, history, and routing actions |
| Page Extension | 70552 | GPI Sales Return Visibility | Document Visibility on Sales Return Order lines |
| Permission Set Extension | 70551 | GPI SALES RETURN DOCS | Adds Sales Return workflow and report permissions |

## Reserved Phase 2 blocks

| Range | Planned use |
|---|---|
| 70553..70559 | Remaining Sales Return support objects and corrections |
| 70560..70569 | Purchase return reports, email workflow, page extensions, and support objects |
| 70570..70579 | Transfer reports, email workflow, page extensions, visibility, and support objects |
| 70580..70589 | Customer Open Order Status report, batch workflow, pages, and support objects |
| 70590..70609 | Shared routing, archive, and Delivery Log support |
| 70610..70649 | Reserved for corrections, tests, and later Phase 2 expansion |

Object IDs are unique within each AL object type. The same numeric ID may be used for different object types when documented here.
