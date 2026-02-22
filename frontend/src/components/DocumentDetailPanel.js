/**
 * DocumentDetailPanel - Side panel for document details
 * 
 * Shows document details in a slide-out panel, including:
 * - Core fields (vendor, invoice, amount, dates)
 * - Workflow status and recent history
 * - Link to full document/PDF
 * - Quick actions based on current status
 */

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  Building2, FileText, DollarSign, Calendar, Hash, 
  ExternalLink, Clock, User, ArrowRight, AlertCircle 
} from 'lucide-react';
import { formatCurrency, formatDate, getQueueConfig, SOURCE_SYSTEM_LABELS } from '@/lib/workflowConstants';

function DetailField({ icon: Icon, label, value, className = '' }) {
  return (
    <div className={`flex items-start gap-3 ${className}`}>
      <div className="p-2 rounded-lg bg-muted">
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="font-medium truncate" title={value || '-'}>{value || '-'}</p>
      </div>
    </div>
  );
}

function WorkflowHistoryEntry({ entry, isLast }) {
  return (
    <div className="relative pl-6">
      {/* Timeline line */}
      {!isLast && (
        <div className="absolute left-[9px] top-6 bottom-0 w-px bg-border" />
      )}
      
      {/* Timeline dot */}
      <div className="absolute left-0 top-1.5 w-[18px] h-[18px] rounded-full border-2 border-background bg-primary/20 flex items-center justify-center">
        <div className="w-2 h-2 rounded-full bg-primary" />
      </div>
      
      <div className="pb-4">
        <div className="flex items-center gap-2 mb-1">
          <Badge variant="outline" className="text-xs">
            {entry.to_status}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {formatDate(entry.timestamp)}
          </span>
        </div>
        {entry.reason && (
          <p className="text-sm text-muted-foreground">{entry.reason}</p>
        )}
        <p className="text-xs text-muted-foreground mt-1">
          <User className="inline h-3 w-3 mr-1" />
          {entry.user || entry.actor || 'system'}
        </p>
      </div>
    </div>
  );
}

export function DocumentDetailPanel({ 
  document, 
  open, 
  onOpenChange, 
  actions = [],
  onNavigateToFull 
}) {
  if (!document) return null;

  const extractedFields = document.extracted_fields || {};
  const queueConfig = getQueueConfig(document.workflow_status);
  
  // Get last 5 workflow history entries
  const workflowHistory = (document.workflow_history || [])
    .slice(-5)
    .reverse();
  
  // Validation errors if any
  const validationErrors = document.validation_errors || [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[400px] sm:w-[540px] p-0" data-testid="document-detail-panel">
        <SheetHeader className="px-6 py-4 border-b">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${queueConfig.color}`}>
              <FileText className="h-5 w-5 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <SheetTitle className="truncate">
                {document.file_name || document.invoice_number_clean || 'Document'}
              </SheetTitle>
              <SheetDescription className="flex items-center gap-2">
                <Badge variant="outline" className={queueConfig.textColor}>
                  {queueConfig.label}
                </Badge>
                <span className="text-xs">
                  {SOURCE_SYSTEM_LABELS[document.source_system] || document.source_system}
                </span>
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-180px)]">
          <div className="px-6 py-4 space-y-6">
            {/* Core Fields */}
            <div className="space-y-4">
              <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                Document Details
              </h4>
              
              <div className="grid gap-4">
                <DetailField
                  icon={Building2}
                  label="Vendor"
                  value={document.vendor_name || document.vendor_raw || extractedFields.vendor}
                />
                
                {(document.vendor_no || document.vendor_canonical) && (
                  <DetailField
                    icon={Hash}
                    label="Vendor ID"
                    value={document.vendor_no || document.vendor_canonical}
                  />
                )}
                
                <DetailField
                  icon={FileText}
                  label="Invoice Number"
                  value={document.invoice_number_clean || document.invoice_number || extractedFields.invoice_number}
                />
                
                <DetailField
                  icon={DollarSign}
                  label="Amount"
                  value={formatCurrency(
                    document.amount_float ?? document.amount ?? extractedFields.total_amount ?? extractedFields.amount
                  )}
                />
                
                <DetailField
                  icon={Calendar}
                  label="Invoice Date"
                  value={formatDate(document.invoice_date || extractedFields.invoice_date)}
                />
                
                {(document.due_date || extractedFields.due_date) && (
                  <DetailField
                    icon={Calendar}
                    label="Due Date"
                    value={formatDate(document.due_date || extractedFields.due_date)}
                  />
                )}
                
                {(document.po_number || extractedFields.po_number) && (
                  <DetailField
                    icon={Hash}
                    label="PO Number"
                    value={document.po_number || extractedFields.po_number}
                  />
                )}
              </div>
            </div>

            <Separator />

            {/* Validation Errors (if any) */}
            {validationErrors.length > 0 && (
              <>
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-red-400 uppercase tracking-wide flex items-center gap-2">
                    <AlertCircle className="h-4 w-4" />
                    Validation Issues
                  </h4>
                  <div className="bg-red-500/10 rounded-lg p-3 space-y-1">
                    {validationErrors.map((error, idx) => (
                      <p key={idx} className="text-sm text-red-400">• {error}</p>
                    ))}
                  </div>
                </div>
                <Separator />
              </>
            )}

            {/* Workflow History */}
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Recent History
              </h4>
              
              {workflowHistory.length > 0 ? (
                <div className="pt-2">
                  {workflowHistory.map((entry, idx) => (
                    <WorkflowHistoryEntry
                      key={idx}
                      entry={entry}
                      isLast={idx === workflowHistory.length - 1}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No history available</p>
              )}
            </div>

            <Separator />

            {/* Document Link */}
            {(document.sharepoint_url || document.legacy_file_reference) && (
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                  Document File
                </h4>
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => window.open(document.sharepoint_url || document.legacy_file_reference, '_blank')}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  View Original Document
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Actions Footer */}
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t bg-background">
          <div className="flex gap-2">
            {actions.map((action, idx) => (
              <Button
                key={idx}
                variant={action.variant || 'default'}
                className="flex-1"
                onClick={() => action.action(document)}
                data-testid={`panel-action-${action.id || idx}`}
              >
                {action.icon && <action.icon className="mr-2 h-4 w-4" />}
                {action.label}
              </Button>
            ))}
            
            {onNavigateToFull && (
              <Button
                variant="outline"
                onClick={() => onNavigateToFull(document.id)}
                data-testid="view-full-detail"
              >
                <ArrowRight className="mr-2 h-4 w-4" />
                Full View
              </Button>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default DocumentDetailPanel;
