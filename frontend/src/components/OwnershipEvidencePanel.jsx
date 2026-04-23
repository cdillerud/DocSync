import { Link } from 'react-router-dom';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { AlertOctagon, ExternalLink, ListChecks, Package, Users, ArrowDown } from 'lucide-react';

const COW_SO_CODE_LABEL = {
  cow_so_uses_base_item: 'Bill on base item',
  cow_so_wrong_customer: 'Wrong customer',
};

const COW_SO_CODE_VARIANT = {
  cow_so_uses_base_item: 'default',
  cow_so_wrong_customer: 'destructive',
};

const OWNERSHIP_LABEL = {
  customer_owned_active: 'CP (active)',
  customer_owned_retired: 'CP (retired)',
  unknown_cp_pattern: 'CP pattern (unregistered)',
};

const CONSIGNMENT_CODE_LABEL = {
  consigned_item_on_ap_invoice: 'AP invoice while consigned',
  consigned_item_wrong_state_on_ap: 'AP invoice on terminal state',
  consigned_item_on_sales_doc: 'Sales doc while consigned',
  consigned_item_post_lifecycle_on_so: 'Sales doc on terminal state',
  consigned_item_wrong_location_on_adj: 'Adj-journal location mismatch',
};

const CONSIGNMENT_STATE_LABEL = {
  consigned_in: 'Consigned In',
  consumed: 'Consumed',
  returned: 'Returned',
};

function scrollToLineForItem(itemNo) {
  return (e) => {
    e.preventDefault();
    const rows = itemNo
      ? document.querySelectorAll(`[data-item-no="${CSS.escape(String(itemNo))}"]`)
      : [];
    if (rows.length === 0) {
      // Fallback: no matching row (e.g., line_items lack item_no). Preserve
      // the legacy container-level scroll + ring so non-targetable lines
      // remain reachable.
      const el = document.getElementById('doc-line-items');
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        el.classList.add('ring-2', 'ring-primary', 'rounded-md');
        setTimeout(() => {
          el.classList.remove('ring-2', 'ring-primary', 'rounded-md');
        }, 1800);
      }
      return;
    }
    // Primary path: scroll the first match into view (block: 'center' for
    // visibility); ring ALL matches simultaneously so duplicate item_no
    // rows are never hidden from the reviewer.
    rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    rows.forEach((r) => r.classList.add('ring-2', 'ring-primary', 'rounded-md'));
    setTimeout(() => {
      rows.forEach((r) =>
        r.classList.remove('ring-2', 'ring-primary', 'rounded-md'),
      );
    }, 1800);
  };
}

function ActionCell({ registryTab, itemNo, testidBase }) {
  return (
    <div className="flex items-center gap-1 justify-end">
      <Link
        to={`/config?tab=${registryTab}&filter_item=${encodeURIComponent(itemNo)}`}
        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-accent"
        data-testid={`${testidBase}-update-registry-${itemNo}`}
      >
        <ExternalLink className="h-3 w-3" />
        Update registry
      </Link>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs"
        onClick={scrollToLineForItem(itemNo)}
        data-testid={`${testidBase}-correct-line-${itemNo}`}
      >
        <ArrowDown className="h-3 w-3 mr-1" />
        Correct line
      </Button>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, count, testid }) {
  return (
    <div className="flex items-center gap-2 text-xs font-semibold text-red-500 mb-1 mt-3" data-testid={testid}>
      <Icon className="h-3.5 w-3.5" />
      <span>{title}</span>
      <Badge variant="destructive" className="h-4 px-1.5 text-[10px]">{count}</Badge>
    </div>
  );
}

export default function OwnershipEvidencePanel({ readiness }) {
  const cowItems = readiness?.cow_items || [];
  const cowSoItems = readiness?.cow_so_items || [];
  const consignedItems = readiness?.consigned_items || [];

  if (cowItems.length === 0 && cowSoItems.length === 0 && consignedItems.length === 0) {
    return null;
  }

  return (
    <div data-testid="ownership-evidence-panel" className="space-y-1 border-t border-border pt-3 mt-3">
      <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground">
        <AlertOctagon className="h-3.5 w-3.5" />
        Ownership evidence
      </div>

      {/* CP on PO */}
      {cowItems.length > 0 && (
        <div data-testid="cow-items-section">
          <SectionHeader icon={Package} title="CP items on PO / Adj-journal" count={cowItems.length} testid="cow-items-header" />
          <div className="space-y-1">
            {cowItems.map((ev, i) => (
              <div
                key={`cow-${ev.item_no}-${i}`}
                data-testid={`cow-items-evidence-${ev.item_no}`}
                className="flex items-center justify-between gap-2 text-xs bg-red-500/5 border border-red-500/20 rounded px-2 py-1.5"
              >
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                  <span className="font-mono truncate">{ev.item_no}</span>
                  <Badge variant="outline" className="text-[10px]">
                    {OWNERSHIP_LABEL[ev.ownership] || ev.ownership}
                  </Badge>
                  {ev.customer_no && (
                    <span className="text-muted-foreground">cust {ev.customer_no}</span>
                  )}
                  {ev.reason === 'adjustment_journal_not_allowed' && (
                    <span className="text-muted-foreground">
                      loc {ev.location || '?'} ≠ canonical {ev.canonical_location || '?'}
                    </span>
                  )}
                </div>
                <ActionCell registryTab="cp-items" itemNo={ev.item_no} testidBase="cow-items" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CP on SO */}
      {cowSoItems.length > 0 && (
        <div data-testid="cow-so-items-section">
          <SectionHeader icon={Users} title="CP items on Sales doc" count={cowSoItems.length} testid="cow-so-items-header" />
          <div className="space-y-1">
            {cowSoItems.map((ev, i) => (
              <div
                key={`cowso-${ev.item_no}-${i}`}
                data-testid={`cow-so-items-evidence-${ev.item_no}`}
                className="flex items-center justify-between gap-2 text-xs bg-red-500/5 border border-red-500/20 rounded px-2 py-1.5"
              >
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                  <span className="font-mono truncate">{ev.item_no}</span>
                  <Badge
                    variant={COW_SO_CODE_VARIANT[ev.blocker_code] || 'outline'}
                    className="text-[10px]"
                  >
                    {COW_SO_CODE_LABEL[ev.blocker_code] || ev.blocker_code}
                  </Badge>
                  {ev.recommended_base_item_no && (
                    <span className="text-muted-foreground">
                      bill as <span className="font-mono text-foreground">{ev.recommended_base_item_no}</span>
                    </span>
                  )}
                  {ev.blocker_code === 'cow_so_wrong_customer' && (
                    <span className="text-muted-foreground">
                      registered {ev.registered_customer_no} · doc {ev.doc_customer_no}
                    </span>
                  )}
                </div>
                <ActionCell registryTab="cp-items" itemNo={ev.item_no} testidBase="cow-so-items" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Consignment */}
      {consignedItems.length > 0 && (
        <div data-testid="consigned-items-section">
          <SectionHeader icon={ListChecks} title="Vendor consignment" count={consignedItems.length} testid="consigned-items-header" />
          <div className="space-y-1">
            {consignedItems.map((ev, i) => (
              <div
                key={`cons-${ev.item_no}-${i}`}
                data-testid={`consigned-items-evidence-${ev.item_no}`}
                className="flex items-center justify-between gap-2 text-xs bg-red-500/5 border border-red-500/20 rounded px-2 py-1.5"
              >
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                  <span className="font-mono truncate">{ev.item_no}</span>
                  <Badge variant="destructive" className="text-[10px]">
                    {CONSIGNMENT_CODE_LABEL[ev.blocker_code] || ev.blocker_code}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {CONSIGNMENT_STATE_LABEL[ev.state] || ev.state}
                  </Badge>
                  {ev.vendor_no && (
                    <span className="text-muted-foreground">vendor {ev.vendor_no}</span>
                  )}
                  {ev.blocker_code === 'consigned_item_wrong_location_on_adj' && (
                    <span className="text-muted-foreground">
                      loc {ev.location || '?'} ≠ physical {ev.physical_location || '?'}
                    </span>
                  )}
                </div>
                <ActionCell registryTab="consigned-items" itemNo={ev.item_no} testidBase="consigned-items" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
