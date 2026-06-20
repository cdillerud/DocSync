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
| Codeunit | 70560 | GPI Purchase Return Email | Vendor Purchase Return Order and warehouse pick-ticket email workflows |
| Report | 70560 | GPI Purchase Return Order | Vendor-facing Purchase Return Order |
| Report | 70561 | GPI Purchase Return Pick | Warehouse-facing Purchase Return Pick Ticket |
| Page Extension | 70560 | GPI Purchase Return Docs | Purchase Return Order email, preview, history, and routing actions |
| Page Extension | 70561 | GPI Purchase Return Visibility | Document Visibility on Purchase Return Order lines |
| Permission Set Extension | 70560 | GPI PURCHASE RETURN DOCS | Adds Purchase Return workflow and report permissions |
| Enum | 70570 | GPI Transfer Visibility | Controls Transfer Pick List and Receipt Notification line visibility |
| Table Extension | 70570 | GPI Transfer Line | Adds Transfer document visibility to Transfer Lines |
| Codeunit | 70570 | GPI Transfer Email | Transfer Pick List and Receipt Notification email workflows |
| Codeunit | 70571 | GPI Transfer Visibility Mgt. | Applies independent pick-list and receipt-notification visibility |
| Report | 70570 | GPI Transfer Pick List | Transfer-from warehouse pick document |
| Report | 70571 | GPI Transfer Receipt Notice | Transfer-to warehouse receipt notification |
| Page Extension | 70570 | GPI Transfer Documents | Transfer Order email, preview, history, and routing actions |
| Page Extension | 70571 | GPI Transfer Visibility | Transfer document visibility on Transfer Order lines |
| Permission Set Extension | 70570 | GPI TRANSFER DOCS | Adds Transfer workflow, visibility, and report permissions |
| Codeunit | 70580 | GPI Customer Open Order Email | Single-customer and batch Open Order Status delivery |
| Report | 70580 | GPI Customer Open Orders | Customer-facing open warehouse and drop-ship order status |
| Table Extension | 70580 | GPI Delivery Log Open Orders | Stores as-of date, order count, line count, and included orders |
| Page Extension | 70580 | GPI Customer Open Orders | Customer Card preview, email, history, and routing actions |
| Page Extension | 70581 | GPI Customer Open Order List | Customer List filtered or selected batch action |
| Page Extension | 70582 | GPI Delivery Log Open Orders | Displays Open Order Status delivery details |
| Permission Set Extension | 70580 | GPI CUSTOMER OPEN ORDERS | Adds Open Order Status workflow and report permissions |
| Codeunit | 70590 | GPI Routing Rule Resolver | Shared customer, vendor, and location rule matching, precedence, date validation, and audit ordering |
| Codeunit | 70591 | GPI Delivery Transport Mgt. | Mockable email editor, email send, and archive upload transport boundary |

## Reserved Phase 2 blocks

| Range | Planned use |
|---|---|
| 70553..70559 | Remaining Sales Return support objects and corrections |
| 70562..70569 | Remaining Purchase Return support objects and corrections |
| 70572..70579 | Remaining Transfer support objects and corrections |
| 70583..70589 | Remaining Customer Open Order support objects and corrections |
| 70592..70609 | Remaining shared routing, archive, transport, and Delivery Log support |
| 70610..70649 | Reserved for corrections, tests, and later expansion |

Object IDs are unique within each AL object type. The same numeric ID may be used for different object types when documented here.
