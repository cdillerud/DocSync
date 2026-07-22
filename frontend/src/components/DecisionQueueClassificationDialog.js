import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertTriangle,
  Loader2,
} from 'lucide-react';

const DOCUMENT_TYPES = [
  ['AP_Invoice', 'AP invoice'],
  ['AR_Invoice', 'AR invoice'],
  ['Credit_Memo', 'Credit memo'],
  ['Remittance', 'Remittance'],
  ['Freight_Document', 'Freight document'],
  ['Sales_Order', 'Sales order / customer PO'],
  ['Sales_Quote', 'Sales quote'],
  ['Order_Confirmation', 'Order confirmation / acknowledgement'],
  ['Warehouse_Receipt', 'Warehouse receipt'],
  ['Inventory_Report', 'Inventory report'],
  ['Shipping_Document', 'Shipping document / packing slip / BOL'],
  ['Quality_Issue', 'Quality issue'],
  ['Inspection_Form', 'Inspection form'],
  ['Return_Request', 'Return request'],
  ['Graphics_Artwork', 'Graphics / artwork'],
  ['Unknown_Document', 'Unknown document'],
];

const MAILBOX_OPTIONS = [
  ['__keep__', 'Keep current mailbox'],
  ['AP', 'AP'],
  ['Operations', 'Operations'],
  ['Sales', 'Sales'],
];

function displayValue(value) {
  return value || 'Not set';
}

export default function DecisionQueueClassificationDialog({
  open,
  onOpenChange,
  fileName,
  currentDocType,
  currentMailboxCategory,
  submitting,
  onSubmit,
}) {
  const [docType, setDocType] = useState('');
  const [mailboxCategory, setMailboxCategory] =
    useState('__keep__');

  useEffect(() => {
    if (open) {
      setDocType(currentDocType || '');
      setMailboxCategory('__keep__');
    }
  }, [
    open,
    currentDocType,
    currentMailboxCategory,
  ]);

  const selectedMailbox = useMemo(
    () =>
      mailboxCategory === '__keep__'
        ? currentMailboxCategory || ''
        : mailboxCategory,
    [mailboxCategory, currentMailboxCategory]
  );

  const mailboxWillChange =
    mailboxCategory !== '__keep__' &&
    mailboxCategory !== currentMailboxCategory;

  const typeWillChange =
    Boolean(docType) &&
    docType !== currentDocType;

  const canSubmit =
    Boolean(docType) &&
    (typeWillChange || mailboxWillChange) &&
    !submitting;

  const handleOpenChange = nextOpen => {
    if (!submitting) {
      onOpenChange(nextOpen);
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;

    const saved = await onSubmit(
      docType,
      mailboxCategory === '__keep__'
        ? undefined
        : mailboxCategory
    );

    if (saved) {
      onOpenChange(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            Change document classification
          </DialogTitle>

          <DialogDescription>
            Correct the document type and, when necessary,
            its routing mailbox.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
            <p className="break-all font-mono text-xs">
              {fileName}
            </p>

            <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-muted-foreground">
                  Current type
                </p>
                <p className="font-medium">
                  {displayValue(currentDocType)}
                </p>
              </div>

              <div>
                <p className="text-muted-foreground">
                  Current mailbox
                </p>
                <p className="font-medium">
                  {displayValue(currentMailboxCategory)}
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="decision-document-type">
              Document type
            </Label>

            <Select
              value={docType}
              onValueChange={setDocType}
              disabled={submitting}
            >
              <SelectTrigger
                id="decision-document-type"
                data-testid="decision-document-type"
              >
                <SelectValue placeholder="Select document type" />
              </SelectTrigger>

              <SelectContent>
                {DOCUMENT_TYPES.map(([value, label]) => (
                  <SelectItem
                    key={value}
                    value={value}
                  >
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="decision-mailbox-category">
              Routing mailbox
            </Label>

            <Select
              value={mailboxCategory}
              onValueChange={setMailboxCategory}
              disabled={submitting}
            >
              <SelectTrigger
                id="decision-mailbox-category"
                data-testid="decision-mailbox-category"
              >
                <SelectValue />
              </SelectTrigger>

              <SelectContent>
                {MAILBOX_OPTIONS.map(([value, label]) => (
                  <SelectItem
                    key={value}
                    value={value}
                  >
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <p className="text-xs text-muted-foreground">
              Effective mailbox: {displayValue(selectedMailbox)}
            </p>
          </div>

          {mailboxWillChange && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />

                <div className="space-y-1 text-xs">
                  <p className="font-medium">
                    This also teaches sender routing.
                  </p>

                  <p className="text-muted-foreground">
                    Future documents from this sender may be routed
                    to {mailboxCategory}. Only change the mailbox
                    when the sender itself was routed incorrectly.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="rounded-md border border-sky-500/30 bg-sky-500/10 p-3 text-xs text-muted-foreground">
            The classification correction is retained as human
            feedback so the classifier can learn from this decision.
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => handleOpenChange(false)}
          >
            Cancel
          </Button>

          <Button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            data-testid="save-classification-correction"
          >
            {submitting && (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            )}
            Save correction
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
