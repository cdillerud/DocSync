import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import { RefreshCw, AlertTriangle, CheckCircle, XCircle, Clock, FileText, User, Building2, DollarSign, ArrowRight, Eye, Edit } from 'lucide-react';
import {
  getWorkflowStatusCounts,
  getVendorPendingQueue,
  getBcValidationPendingQueue,
  getBcValidationFailedQueue,
  getDataCorrectionPendingQueue,
  getReadyForApprovalQueue,
  setVendor,
  updateFields,
  overrideBcValidation,
  approveDocument,
  rejectDocument
} from '@/lib/api';

const STATUS_CONFIG = {
  vendor_pending: { label: 'Vendor Pending', color: 'bg-yellow-500', icon: User, description: 'Awaiting vendor match' },
  bc_validation_pending: { label: 'BC Validation', color: 'bg-blue-500', icon: Building2, description: 'Validating in Business Central' },
  bc_validation_failed: { label: 'Validation Failed', color: 'bg-red-500', icon: AlertTriangle, description: 'BC validation errors' },
  data_correction_pending: { label: 'Data Correction', color: 'bg-orange-500', icon: Edit, description: 'Needs manual data fix' },
  ready_for_approval: { label: 'Ready for Approval', color: 'bg-green-500', icon: CheckCircle, description: 'Awaiting approval' },
  approval_in_progress: { label: 'Approval In Progress', color: 'bg-purple-500', icon: Clock, description: 'Being reviewed' },
  approved: { label: 'Approved', color: 'bg-emerald-500', icon: CheckCircle, description: 'Approved and ready' },
  rejected: { label: 'Rejected', color: 'bg-red-700', icon: XCircle, description: 'Rejected' },
  exported: { label: 'Exported', color: 'bg-slate-500', icon: ArrowRight, description: 'Exported to BC' },
};

function QueueCount({ status, count, onClick }) {
  const config = STATUS_CONFIG[status] || { label: status, color: 'bg-gray-500', icon: FileText };
  const Icon = config.icon;
  
  return (
    <Card 
      className="cursor-pointer hover:border-primary transition-colors" 
      onClick={onClick}
      data-testid={`queue-card-${status}`}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${config.color}`}>
              <Icon className="h-4 w-4 text-white" />
            </div>
            <div>
              <p className="text-sm font-medium">{config.label}</p>
              <p className="text-xs text-muted-foreground">{config.description}</p>
            </div>
          </div>
          <div className="text-2xl font-bold">{count}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function DocumentRow({ doc, onAction, onViewDetail }) {
  const extractedFields = doc.extracted_fields || {};
  const amount = doc.amount_float || extractedFields.amount;
  
  return (
    <TableRow data-testid={`doc-row-${doc.id}`}>
      <TableCell className="font-medium max-w-[200px] truncate">{doc.file_name}</TableCell>
      <TableCell>{doc.vendor_raw || extractedFields.vendor || '-'}</TableCell>
      <TableCell>{doc.invoice_number_clean || extractedFields.invoice_number || '-'}</TableCell>
      <TableCell className="text-right">
        {amount ? `$${Number(amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}` : '-'}
      </TableCell>
      <TableCell>
        <Badge variant="outline" className="text-xs">
          {doc.workflow_status || 'unknown'}
        </Badge>
      </TableCell>
      <TableCell>{new Date(doc.created_utc).toLocaleDateString()}</TableCell>
      <TableCell className="text-right">
        <div className="flex gap-1 justify-end">
          <Button variant="ghost" size="sm" onClick={() => onViewDetail(doc.id)} data-testid={`view-doc-${doc.id}`}>
            <Eye className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => onAction(doc)} data-testid={`action-doc-${doc.id}`}>
            Action
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function SetVendorDialog({ doc, open, onOpenChange, onComplete }) {
  const [vendorNo, setVendorNo] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!vendorNo.trim()) {
      toast.error('Vendor number is required');
      return;
    }
    setLoading(true);
    try {
      await setVendor(doc.id, vendorNo.trim(), vendorName.trim(), 'hub_user');
      toast.success('Vendor set successfully');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to set vendor');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="set-vendor-dialog">
        <DialogHeader>
          <DialogTitle>Set Vendor</DialogTitle>
          <DialogDescription>
            Assign a BC vendor to document: {doc?.file_name}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Extracted Vendor Name</Label>
            <p className="text-sm text-muted-foreground">{doc?.vendor_raw || doc?.extracted_fields?.vendor || 'Not extracted'}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendorNo">BC Vendor Number *</Label>
            <Input 
              id="vendorNo" 
              value={vendorNo} 
              onChange={(e) => setVendorNo(e.target.value)}
              placeholder="e.g., V10001"
              data-testid="vendor-no-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendorName">Vendor Display Name</Label>
            <Input 
              id="vendorName" 
              value={vendorName} 
              onChange={(e) => setVendorName(e.target.value)}
              placeholder="e.g., ACME Supplies Inc."
              data-testid="vendor-name-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading} data-testid="set-vendor-submit">
            {loading ? 'Saving...' : 'Set Vendor'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OverrideValidationDialog({ doc, open, onOpenChange, onComplete }) {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!reason.trim()) {
      toast.error('Override reason is required');
      return;
    }
    setLoading(true);
    try {
      await overrideBcValidation(doc.id, reason.trim(), 'hub_user');
      toast.success('Validation override applied');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to override validation');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="override-validation-dialog">
        <DialogHeader>
          <DialogTitle>Override BC Validation</DialogTitle>
          <DialogDescription>
            Allow this document to proceed despite validation failures.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Document</Label>
            <p className="text-sm text-muted-foreground">{doc?.file_name}</p>
          </div>
          <div className="space-y-2">
            <Label>Validation Errors</Label>
            <div className="text-sm text-red-400">
              {(doc?.validation_errors || []).map((err, i) => (
                <p key={i}>- {err}</p>
              ))}
              {(!doc?.validation_errors || doc.validation_errors.length === 0) && <p>No specific errors recorded</p>}
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">Override Reason *</Label>
            <Textarea 
              id="reason" 
              value={reason} 
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this validation should be overridden..."
              data-testid="override-reason-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="destructive" onClick={handleSubmit} disabled={loading} data-testid="override-submit">
            {loading ? 'Applying...' : 'Override & Continue'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ApprovalDialog({ doc, open, onOpenChange, onComplete }) {
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState('approve');

  const handleSubmit = async () => {
    setLoading(true);
    try {
      if (action === 'approve') {
        await approveDocument(doc.id, comment.trim(), 'hub_user');
        toast.success('Document approved');
      } else {
        if (!comment.trim()) {
          toast.error('Rejection reason is required');
          setLoading(false);
          return;
        }
        await rejectDocument(doc.id, comment.trim(), 'hub_user');
        toast.success('Document rejected');
      }
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || `Failed to ${action} document`);
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="approval-dialog">
        <DialogHeader>
          <DialogTitle>Approve or Reject</DialogTitle>
          <DialogDescription>
            Review and decide on: {doc?.file_name}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><span className="text-muted-foreground">Vendor:</span> {doc?.vendor_canonical || doc?.vendor_raw || '-'}</div>
            <div><span className="text-muted-foreground">Invoice #:</span> {doc?.invoice_number_clean || '-'}</div>
            <div><span className="text-muted-foreground">Amount:</span> {doc?.amount_float ? `$${doc.amount_float.toLocaleString()}` : '-'}</div>
            <div><span className="text-muted-foreground">Confidence:</span> {doc?.ai_confidence ? `${(doc.ai_confidence * 100).toFixed(0)}%` : '-'}</div>
          </div>
          <div className="flex gap-4">
            <Button 
              variant={action === 'approve' ? 'default' : 'outline'} 
              onClick={() => setAction('approve')}
              className="flex-1"
              data-testid="action-approve"
            >
              <CheckCircle className="mr-2 h-4 w-4" /> Approve
            </Button>
            <Button 
              variant={action === 'reject' ? 'destructive' : 'outline'} 
              onClick={() => setAction('reject')}
              className="flex-1"
              data-testid="action-reject"
            >
              <XCircle className="mr-2 h-4 w-4" /> Reject
            </Button>
          </div>
          <div className="space-y-2">
            <Label htmlFor="comment">{action === 'approve' ? 'Comment (optional)' : 'Rejection Reason *'}</Label>
            <Textarea 
              id="comment" 
              value={comment} 
              onChange={(e) => setComment(e.target.value)}
              placeholder={action === 'approve' ? 'Optional approval notes...' : 'Explain why this is being rejected...'}
              data-testid="approval-comment-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button 
            variant={action === 'approve' ? 'default' : 'destructive'} 
            onClick={handleSubmit} 
            disabled={loading}
            data-testid="approval-submit"
          >
            {loading ? 'Processing...' : action === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DataCorrectionDialog({ doc, open, onOpenChange, onComplete }) {
  const [fields, setFields] = useState({
    vendor: doc?.extracted_fields?.vendor || doc?.vendor_raw || '',
    invoice_number: doc?.extracted_fields?.invoice_number || doc?.invoice_number_clean || '',
    amount: doc?.extracted_fields?.amount || doc?.amount_float || '',
    invoice_date: doc?.extracted_fields?.invoice_date || ''
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (doc) {
      setFields({
        vendor: doc?.extracted_fields?.vendor || doc?.vendor_raw || '',
        invoice_number: doc?.extracted_fields?.invoice_number || doc?.invoice_number_clean || '',
        amount: doc?.extracted_fields?.amount || doc?.amount_float || '',
        invoice_date: doc?.extracted_fields?.invoice_date || ''
      });
    }
  }, [doc]);

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await updateFields(doc.id, {
        vendor: fields.vendor,
        invoice_number: fields.invoice_number,
        amount: parseFloat(fields.amount) || null,
        invoice_date: fields.invoice_date || null
      }, 'hub_user');
      toast.success('Fields updated successfully');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to update fields');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="data-correction-dialog">
        <DialogHeader>
          <DialogTitle>Correct Document Data</DialogTitle>
          <DialogDescription>
            Update extracted fields for: {doc?.file_name}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="vendor">Vendor Name</Label>
            <Input 
              id="vendor" 
              value={fields.vendor} 
              onChange={(e) => setFields({...fields, vendor: e.target.value})}
              data-testid="correction-vendor-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invoice_number">Invoice Number</Label>
            <Input 
              id="invoice_number" 
              value={fields.invoice_number} 
              onChange={(e) => setFields({...fields, invoice_number: e.target.value})}
              data-testid="correction-invoice-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="amount">Amount</Label>
            <Input 
              id="amount" 
              type="number"
              step="0.01"
              value={fields.amount} 
              onChange={(e) => setFields({...fields, amount: e.target.value})}
              data-testid="correction-amount-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invoice_date">Invoice Date</Label>
            <Input 
              id="invoice_date" 
              type="date"
              value={fields.invoice_date} 
              onChange={(e) => setFields({...fields, invoice_date: e.target.value})}
              data-testid="correction-date-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading} data-testid="correction-submit">
            {loading ? 'Saving...' : 'Save & Continue'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function WorkflowQueuesPage() {
  const navigate = useNavigate();
  const [statusCounts, setStatusCounts] = useState({});
  const [activeTab, setActiveTab] = useState('vendor_pending');
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  
  // Dialogs
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [vendorDialogOpen, setVendorDialogOpen] = useState(false);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
  const [correctionDialogOpen, setCorrectionDialogOpen] = useState(false);

  const fetchStatusCounts = async () => {
    try {
      const res = await getWorkflowStatusCounts();
      setStatusCounts(res.data.status_counts || {});
    } catch (err) {
      console.error('Failed to fetch status counts:', err);
    }
  };

  const fetchQueueDocuments = async (queue) => {
    setLoading(true);
    try {
      let res;
      switch (queue) {
        case 'vendor_pending':
          res = await getVendorPendingQueue({ limit: 50 });
          break;
        case 'bc_validation_pending':
          res = await getBcValidationPendingQueue({ limit: 50 });
          break;
        case 'bc_validation_failed':
          res = await getBcValidationFailedQueue({ limit: 50 });
          break;
        case 'data_correction_pending':
          res = await getDataCorrectionPendingQueue({ limit: 50 });
          break;
        case 'ready_for_approval':
          res = await getReadyForApprovalQueue({ limit: 50 });
          break;
        default:
          res = { data: { documents: [], total: 0 } };
      }
      setDocuments(res.data.documents || []);
      setTotal(res.data.total || 0);
    } catch (err) {
      toast.error('Failed to load queue');
      setDocuments([]);
      setTotal(0);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchStatusCounts();
  }, []);

  useEffect(() => {
    fetchQueueDocuments(activeTab);
  }, [activeTab]);

  const handleRefresh = () => {
    fetchStatusCounts();
    fetchQueueDocuments(activeTab);
  };

  const handleAction = (doc) => {
    setSelectedDoc(doc);
    // Open appropriate dialog based on workflow status
    switch (doc.workflow_status) {
      case 'vendor_pending':
        setVendorDialogOpen(true);
        break;
      case 'bc_validation_failed':
        setOverrideDialogOpen(true);
        break;
      case 'data_correction_pending':
        setCorrectionDialogOpen(true);
        break;
      case 'ready_for_approval':
      case 'approval_in_progress':
        setApprovalDialogOpen(true);
        break;
      default:
        navigate(`/documents/${doc.id}`);
    }
  };

  const handleComplete = () => {
    handleRefresh();
  };

  const handleViewDetail = (docId) => {
    navigate(`/documents/${docId}`);
  };

  const exceptionQueues = ['vendor_pending', 'bc_validation_failed', 'data_correction_pending', 'bc_validation_pending'];
  const approvalQueues = ['ready_for_approval', 'approval_in_progress'];

  return (
    <div className="space-y-6" data-testid="workflow-queues-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">AP Invoice Workflow</h1>
          <p className="text-muted-foreground">Manage exception queues and approvals</p>
        </div>
        <Button onClick={handleRefresh} variant="outline" data-testid="refresh-queues">
          <RefreshCw className="mr-2 h-4 w-4" /> Refresh
        </Button>
      </div>

      {/* Status Overview */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {Object.entries(STATUS_CONFIG).slice(0, 5).map(([status, config]) => (
          <QueueCount 
            key={status}
            status={status}
            count={statusCounts[status] || 0}
            onClick={() => setActiveTab(status)}
          />
        ))}
      </div>

      {/* Queue Tabs */}
      <Card>
        <CardHeader>
          <CardTitle>Exception & Approval Queues</CardTitle>
          <CardDescription>Documents requiring manual intervention</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-4 flex flex-wrap h-auto gap-1">
              <TabsTrigger value="vendor_pending" data-testid="tab-vendor-pending">
                Vendor Pending ({statusCounts.vendor_pending || 0})
              </TabsTrigger>
              <TabsTrigger value="bc_validation_pending" data-testid="tab-bc-validation-pending">
                BC Validation ({statusCounts.bc_validation_pending || 0})
              </TabsTrigger>
              <TabsTrigger value="bc_validation_failed" data-testid="tab-bc-validation-failed">
                Validation Failed ({statusCounts.bc_validation_failed || 0})
              </TabsTrigger>
              <TabsTrigger value="data_correction_pending" data-testid="tab-data-correction">
                Data Correction ({statusCounts.data_correction_pending || 0})
              </TabsTrigger>
              <TabsTrigger value="ready_for_approval" data-testid="tab-ready-for-approval">
                Ready for Approval ({statusCounts.ready_for_approval || 0})
              </TabsTrigger>
            </TabsList>

            {['vendor_pending', 'bc_validation_pending', 'bc_validation_failed', 'data_correction_pending', 'ready_for_approval'].map(queue => (
              <TabsContent key={queue} value={queue}>
                {loading ? (
                  <div className="flex items-center justify-center py-8">
                    <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : documents.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <FileText className="mx-auto h-12 w-12 mb-4 opacity-50" />
                    <p>No documents in this queue</p>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>File Name</TableHead>
                        <TableHead>Vendor</TableHead>
                        <TableHead>Invoice #</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Date</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {documents.map(doc => (
                        <DocumentRow 
                          key={doc.id} 
                          doc={doc} 
                          onAction={handleAction}
                          onViewDetail={handleViewDetail}
                        />
                      ))}
                    </TableBody>
                  </Table>
                )}
                {!loading && total > documents.length && (
                  <p className="text-sm text-muted-foreground mt-4 text-center">
                    Showing {documents.length} of {total} documents
                  </p>
                )}
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      {/* Dialogs */}
      <SetVendorDialog 
        doc={selectedDoc} 
        open={vendorDialogOpen} 
        onOpenChange={setVendorDialogOpen}
        onComplete={handleComplete}
      />
      <OverrideValidationDialog 
        doc={selectedDoc} 
        open={overrideDialogOpen} 
        onOpenChange={setOverrideDialogOpen}
        onComplete={handleComplete}
      />
      <ApprovalDialog 
        doc={selectedDoc} 
        open={approvalDialogOpen} 
        onOpenChange={setApprovalDialogOpen}
        onComplete={handleComplete}
      />
      <DataCorrectionDialog 
        doc={selectedDoc} 
        open={correctionDialogOpen} 
        onOpenChange={setCorrectionDialogOpen}
        onComplete={handleComplete}
      />
    </div>
  );
}
