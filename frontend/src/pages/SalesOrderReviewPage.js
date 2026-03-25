import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  DialogDescription,
} from '../components/ui/dialog';
import { Textarea } from '../components/ui/textarea';
import { toast } from 'sonner';
import {
  Loader2, CheckCircle2, Flag, ArrowLeft, ExternalLink,
  FileText, XCircle,
} from 'lucide-react';
import CreateBCSalesOrderPanel from '../components/CreateBCSalesOrderPanel';

const API = process.env.REACT_APP_BACKEND_URL;

export default function SalesOrderReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [flagDialog, setFlagDialog] = useState(false);
  const [flagReason, setFlagReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  const fetchDoc = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/documents/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error('Document not found');
      const data = await res.json();
      setDoc(data.document || data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchDoc(); }, [fetchDoc]);

  const handleApprove = async () => {
    setActionLoading(true);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/review/${encodeURIComponent(id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'approve' }),
      });
      if (!res.ok) throw new Error('Approve failed');
      toast.success('Document approved');
      await fetchDoc();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleFlag = async () => {
    if (!flagReason.trim()) return;
    setActionLoading(true);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/review/${encodeURIComponent(id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'flag', reason: flagReason }),
      });
      if (!res.ok) throw new Error('Flag failed');
      toast.success('Document flagged');
      setFlagDialog(false);
      setFlagReason('');
      await fetchDoc();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <XCircle className="w-12 h-12 text-muted-foreground" />
        <p className="text-muted-foreground">Document not found</p>
        <Button variant="outline" onClick={() => navigate(-1)}>
          <ArrowLeft className="w-4 h-4 mr-2" /> Go Back
        </Button>
      </div>
    );
  }

  const ef = doc.extracted_fields || {};
  const reviewStatus = doc.sales_review_status || 'pending_rep_review';
  const isApproved = reviewStatus === 'approved';
  const isFlagged = reviewStatus === 'flagged';

  return (
    <div className="max-w-3xl mx-auto py-6 px-4 space-y-4" data-testid="sales-order-review-page">
      {/* Header bar */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)} data-testid="review-back-btn">
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold">PO Review</h1>
              {ef.po_number && (
                <Badge variant="outline" className="font-mono text-xs">{ef.po_number}</Badge>
              )}
              {isApproved && (
                <Badge className="bg-emerald-600 text-white text-xs">
                  <CheckCircle2 className="w-3 h-3 mr-1" /> Approved
                </Badge>
              )}
              {isFlagged && (
                <Badge className="bg-red-600 text-white text-xs">
                  <Flag className="w-3 h-3 mr-1" /> Flagged
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {ef.customer_name || doc.vendor_canonical || 'Unknown Customer'}
              {ef.total_amount ? ` — $${Number(ef.total_amount).toLocaleString()}` : ''}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link
            to={`/documents/${encodeURIComponent(id)}`}
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
            data-testid="view-full-detail-link"
          >
            <FileText className="w-3.5 h-3.5" /> Full Detail <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      </div>

      {/* BC Sales Order Panel — the main review content */}
      <CreateBCSalesOrderPanel document={doc} onUpdate={fetchDoc} autoRun forceShow />

      {/* Approve / Flag actions */}
      {!isApproved && (
        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                {isFlagged
                  ? `Flagged: ${doc.sales_flag_reason || 'No reason given'}`
                  : 'Review complete? Approve or flag this document.'}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="text-red-500 border-red-500/30 hover:bg-red-500/10"
                  onClick={() => setFlagDialog(true)}
                  disabled={actionLoading}
                  data-testid="review-flag-btn"
                >
                  <Flag className="w-4 h-4 mr-1.5" /> Flag
                </Button>
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={handleApprove}
                  disabled={actionLoading}
                  data-testid="review-approve-btn"
                >
                  {actionLoading ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <CheckCircle2 className="w-4 h-4 mr-1.5" />}
                  Approve
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Flag dialog */}
      <Dialog open={flagDialog} onOpenChange={setFlagDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Flag Document</DialogTitle>
            <DialogDescription>
              Provide a reason for flagging PO {ef.po_number || id.slice(0, 12)}.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Reason for flagging..."
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
            className="min-h-[80px]"
            data-testid="flag-reason-input"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setFlagDialog(false)}>Cancel</Button>
            <Button
              className="bg-red-600 hover:bg-red-700 text-white"
              onClick={handleFlag}
              disabled={!flagReason.trim() || actionLoading}
              data-testid="flag-submit-btn"
            >
              {actionLoading ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Flag className="w-4 h-4 mr-1.5" />}
              Flag Document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
