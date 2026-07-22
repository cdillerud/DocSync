import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
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
import { AlertTriangle, Loader2 } from 'lucide-react';

const DISPOSITION_REASONS = [
  {
    value: 'graphics_artwork',
    label: 'Graphics / artwork',
    description:
      'Packaging artwork, dielines, label proofs, print layouts, or other production graphics.',
  },
  {
    value: 'duplicate_document',
    label: 'Duplicate document',
    description:
      'A retained copy already exists, so this copy should not be processed again.',
  },
  {
    value: 'spam_irrelevant',
    label: 'Spam / irrelevant',
    description:
      'The document is unrelated to an operational business process.',
  },
  {
    value: 'unsupported_document',
    label: 'Unsupported document',
    description:
      'The document is legitimate, but this workflow does not support processing it.',
  },
  {
    value: 'not_business_document',
    label: 'Not a business document',
    description:
      'The file does not represent a business transaction or operational record.',
  },
  {
    value: 'other',
    label: 'Other',
    description:
      'Another reason not listed above. Notes are required.',
  },
];

export default function NonTransactionalDispositionDialog({
  open,
  onOpenChange,
  fileName,
  submitting,
  onSubmit,
}) {
  const [reasonValue, setReasonValue] = useState('');
  const [notes, setNotes] = useState('');

  const selectedReason = useMemo(
    () =>
      DISPOSITION_REASONS.find(
        reason => reason.value === reasonValue
      ),
    [reasonValue]
  );

  const notesRequired = reasonValue === 'other';
  const canSubmit =
    Boolean(selectedReason) &&
    (!notesRequired || Boolean(notes.trim())) &&
    !submitting;

  useEffect(() => {
    if (!open) {
      setReasonValue('');
      setNotes('');
    }
  }, [open]);

  const handleOpenChange = nextOpen => {
    if (!submitting) {
      onOpenChange(nextOpen);
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;

    const saved = await onSubmit(
      selectedReason,
      notes.trim()
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
            Exclude from processing
          </DialogTitle>

          <DialogDescription>
            Choose why this document should be removed from
            operational processing.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />

              <div className="space-y-1 text-sm">
                <p className="font-medium">
                  The original file will be retained.
                </p>

                <p className="text-xs text-muted-foreground">
                  The document and audit history remain available,
                  but Business Central, routing, workflow, and further
                  operational processing will be blocked.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="non-transactional-reason">
              Reason
            </Label>

            <Select
              value={reasonValue}
              onValueChange={setReasonValue}
              disabled={submitting}
            >
              <SelectTrigger
                id="non-transactional-reason"
                data-testid="non-transactional-reason"
              >
                <SelectValue placeholder="Select a reason" />
              </SelectTrigger>

              <SelectContent>
                {DISPOSITION_REASONS.map(reason => (
                  <SelectItem
                    key={reason.value}
                    value={reason.value}
                  >
                    {reason.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selectedReason && (
            <div className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
              <p>{selectedReason.description}</p>

              {selectedReason.value ===
              'graphics_artwork' ? (
                <p className="mt-2">
                  This selection also records a classifier
                  correction so similar artwork can be recognized
                  later. It does not create a sender or vendor
                  blacklist.
                </p>
              ) : (
                <p className="mt-2">
                  This selection records the disposition for audit
                  and reporting, but does not change the document
                  classifier type.
                </p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="non-transactional-notes">
              Notes
              {notesRequired ? ' — required' : ' — optional'}
            </Label>

            <Textarea
              id="non-transactional-notes"
              value={notes}
              onChange={event =>
                setNotes(event.target.value)
              }
              disabled={submitting}
              placeholder={
                notesRequired
                  ? 'Explain why this document should be excluded'
                  : 'Add any useful context'
              }
              rows={3}
              data-testid="non-transactional-notes"
            />
          </div>

          <p className="break-all font-mono text-xs text-muted-foreground">
            {fileName}
          </p>
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
            variant="destructive"
            disabled={!canSubmit}
            onClick={handleSubmit}
            data-testid="confirm-non-transactional-disposition"
          >
            {submitting && (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            )}
            Exclude document
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
