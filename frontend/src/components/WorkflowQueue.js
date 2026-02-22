/**
 * WorkflowQueue - Reusable workflow queue component
 * 
 * A generic queue component that can be used for any document type.
 * It handles:
 * - Fetching documents via the generic queue API
 * - Displaying documents in a table
 * - Row actions (passed as props)
 * - Pagination
 * 
 * Usage:
 *   <WorkflowQueue
 *     docType="AP_INVOICE"
 *     status="vendor_pending"
 *     title="Vendor Pending"
 *     filters={{ vendor: 'ACME' }}
 *     rowActions={[{ label: 'Set Vendor', action: handleSetVendor }]}
 *     onDocumentSelect={(doc) => setSelectedDoc(doc)}
 *   />
 */

import { useState, useEffect, useCallback } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, FileText, Eye, MoreVertical, ChevronLeft, ChevronRight } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { getGenericQueue } from '@/lib/api';
import { formatCurrency, formatDate, calculateAgeDays, getQueueConfig, SOURCE_SYSTEM_LABELS } from '@/lib/workflowConstants';

const PAGE_SIZE = 25;

export function WorkflowQueue({
  docType,
  status,
  title,
  filters = {},
  rowActions = [],
  onDocumentSelect,
  onRefreshNeeded,
  refreshTrigger = 0,
}) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState(null);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        status,
        page,
        page_size: PAGE_SIZE,
        ...filters,
      };
      
      // Remove empty filter values
      Object.keys(params).forEach(key => {
        if (params[key] === '' || params[key] === null || params[key] === undefined) {
          delete params[key];
        }
      });

      const res = await getGenericQueue(docType, params);
      setDocuments(res.data.documents || []);
      setTotal(res.data.total || 0);
    } catch (err) {
      console.error('Failed to fetch queue:', err);
      setError(err.response?.data?.detail || 'Failed to load queue');
      toast.error('Failed to load queue');
      setDocuments([]);
      setTotal(0);
    }
    setLoading(false);
  }, [docType, status, page, filters]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);

  const handleRefresh = () => {
    setPage(1);
    fetchDocuments();
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const queueConfig = getQueueConfig(status);

  return (
    <div className="space-y-4" data-testid={`workflow-queue-${status}`}>
      {/* Queue Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-8 rounded-full ${queueConfig.color}`} />
          <div>
            <h3 className="font-semibold">{title || queueConfig.label}</h3>
            <p className="text-xs text-muted-foreground">
              {total} document{total !== 1 ? 's' : ''} {queueConfig.description && `• ${queueConfig.description}`}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRefresh}
          disabled={loading}
          data-testid={`refresh-queue-${status}`}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Error State */}
      {error && (
        <div className="p-4 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}

      {/* Loading State */}
      {loading && documents.length === 0 && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Empty State */}
      {!loading && documents.length === 0 && !error && (
        <div className="text-center py-12 text-muted-foreground">
          <FileText className="mx-auto h-12 w-12 mb-4 opacity-50" />
          <p>No documents in this queue</p>
        </div>
      )}

      {/* Document Table */}
      {documents.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[180px]">Vendor</TableHead>
                <TableHead className="w-[120px]">Invoice #</TableHead>
                <TableHead className="text-right w-[100px]">Amount</TableHead>
                <TableHead className="w-[100px]">Invoice Date</TableHead>
                <TableHead className="w-[80px]">Source</TableHead>
                <TableHead className="w-[60px]">Age</TableHead>
                <TableHead className="text-right w-[100px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <WorkflowQueueRow
                  key={doc.id}
                  doc={doc}
                  rowActions={rowActions}
                  onSelect={() => onDocumentSelect?.(doc)}
                />
              ))}
            </TableBody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t">
              <p className="text-sm text-muted-foreground">
                Showing {((page - 1) * PAGE_SIZE) + 1}-{Math.min(page * PAGE_SIZE, total)} of {total}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1 || loading}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm">Page {page} of {totalPages}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages || loading}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function WorkflowQueueRow({ doc, rowActions, onSelect }) {
  const extractedFields = doc.extracted_fields || {};
  const vendorName = doc.vendor_name || doc.vendor_raw || extractedFields.vendor || '-';
  const vendorNo = doc.vendor_no || doc.vendor_canonical || '';
  const invoiceNumber = doc.invoice_number_clean || doc.invoice_number || extractedFields.invoice_number || '-';
  const amount = doc.amount_float ?? doc.amount ?? extractedFields.total_amount ?? extractedFields.amount;
  const invoiceDate = doc.invoice_date || extractedFields.invoice_date;
  const sourceSystem = doc.source_system || 'UNKNOWN';
  const ageDays = calculateAgeDays(doc.workflow_status_updated_utc || doc.created_utc);

  return (
    <TableRow
      className="cursor-pointer hover:bg-muted/50"
      data-testid={`queue-row-${doc.id}`}
    >
      <TableCell onClick={onSelect}>
        <div className="max-w-[180px]">
          <p className="font-medium truncate" title={vendorName}>{vendorName}</p>
          {vendorNo && <p className="text-xs text-muted-foreground">{vendorNo}</p>}
        </div>
      </TableCell>
      <TableCell onClick={onSelect}>
        <span className="font-mono text-sm">{invoiceNumber}</span>
      </TableCell>
      <TableCell className="text-right" onClick={onSelect}>
        {formatCurrency(amount)}
      </TableCell>
      <TableCell onClick={onSelect}>
        {formatDate(invoiceDate)}
      </TableCell>
      <TableCell onClick={onSelect}>
        <Badge variant="outline" className="text-xs">
          {SOURCE_SYSTEM_LABELS[sourceSystem] || sourceSystem}
        </Badge>
      </TableCell>
      <TableCell onClick={onSelect}>
        {ageDays !== null ? (
          <span className={`text-sm ${ageDays > 7 ? 'text-red-400' : ageDays > 3 ? 'text-yellow-400' : 'text-muted-foreground'}`}>
            {ageDays}d
          </span>
        ) : '-'}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onSelect}
            data-testid={`view-doc-${doc.id}`}
          >
            <Eye className="h-4 w-4" />
          </Button>
          
          {rowActions.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  data-testid={`action-menu-${doc.id}`}
                >
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {rowActions.map((action, idx) => (
                  <DropdownMenuItem
                    key={idx}
                    onClick={() => action.action(doc)}
                    data-testid={`action-${action.id || idx}-${doc.id}`}
                  >
                    {action.icon && <action.icon className="mr-2 h-4 w-4" />}
                    {action.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

export default WorkflowQueue;
