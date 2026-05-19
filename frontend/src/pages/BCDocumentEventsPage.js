import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { toast } from 'sonner';
import { AlertCircle, CheckCircle2, ExternalLink, FileClock, RefreshCw, Search, Send, ShieldCheck, Wrench } from 'lucide-react';

const SAMPLE_DELIVERY_EVENT = {
  event_id: 'sample-delivery-sent-001',
  idempotency_key: 'sample-document-delivery-001',
  correlation_id: 'sandbox-bc-delivery-test-001',
  event_timestamp: '2026-05-18T21:15:00Z',
  source_app: 'BC_AL_EXTENSION_SANDBOX',
  source_system: 'BC_NATIVE',
  actor: 'sandbox-user',
  bc_record: {
    company_id: 'sandbox-company-id',
    company_name: 'Sandbox Company',
    environment: 'Sandbox',
    record_type: 'Posted Sales Invoice',
    record_id: 'sandbox-record-guid',
    record_no: 'SAMPLE-INV-001',
    record_system_id: 'sandbox-system-id',
    posted: true,
  },
  document_no: 'SAMPLE-INV-001',
  document_type: 'SALES_INVOICE',
  file_name: 'SAMPLE-INV-001.pdf',
  delivery_method: 'bc_email',
  delivery_status: 'sent',
  template_code: 'SALES_INVOICE_DEFAULT',
  subject: 'Sandbox Invoice SAMPLE-INV-001',
  email_message_id: 'sandbox-message-id-001',
  recipient_resolution_method: 'master_record_fallback',
  recipients: {
    to: ['recipient@example.invalid'],
    cc: [],
    bcc: [],
  },
  sharepoint: {
    site_id: 'sandbox-site-id',
    drive_id: 'sandbox-drive-id',
    item_id: 'sandbox-item-id',
    web_url: null,
    folder_path: 'BC/Customer/SAMPLE/Sales Invoice/2026/SAMPLE-INV-001',
    file_name: 'SAMPLE-INV-001.pdf',
    storage_status: 'synced',
  },
  metadata: {
    test_payload: true,
    notes: 'Sanitized sandbox test event for BC document delivery integration',
  },
};

function formatDate(value) {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function statusVariant(value) {
  if (value === true || value === 'sent' || value === 'exported' || value === 'ready' || value === 'external_link' || value === 'healthy' || value === 'verified') return 'default';
  if (value === false || value === 0 || value === 'captured' || value === 'missing' || value === 'unchecked') return 'secondary';
  return 'outline';
}

function linkHealthVariant(status) {
  if (status === 'verified') return 'default';
  if (status === 'auth_required' || status === 'unchecked') return 'secondary';
  if (status === 'missing' || status === 'invalid' || status === 'unreachable') return 'destructive';
  return 'outline';
}

function getLinkHealth(doc) {
  const storedHealth = doc?.link_health || doc?.sharepoint?.link_health;
  if (storedHealth) {
    return {
      state: storedHealth.status || 'unchecked',
      label: storedHealth.label || storedHealth.status || 'Link health stored',
      detail: storedHealth.detail || storedHealth.web_url || 'Stored link health result',
      checkedAt: storedHealth.checked_at,
      variant: linkHealthVariant(storedHealth.status),
    };
  }

  const sharepoint = doc?.sharepoint || {};
  const webUrl = (sharepoint.web_url || '').trim();
  const folderPath = (sharepoint.folder_path || '').trim();
  const fileName = (sharepoint.file_name || doc?.file_name || '').trim();
  const issues = [];

  if (!webUrl) issues.push('Missing URL');
  if (webUrl && !/^https?:\/\//i.test(webUrl)) issues.push('URL is not HTTP/HTTPS');
  if (webUrl && /^\s*Document Link Template:/i.test(webUrl)) issues.push('Template label included in URL');
  if (!folderPath) issues.push('Missing folder path');
  if (folderPath && /^\s*Document Folder Template:/i.test(folderPath)) issues.push('Template label included in folder');
  if (fileName && webUrl && !webUrl.toLowerCase().includes(fileName.toLowerCase())) issues.push('URL does not include file name');

  if (!webUrl && !folderPath) {
    return {
      state: 'missing',
      label: 'No link',
      detail: 'No external SharePoint/Zetadocs link stored yet',
      variant: 'secondary',
    };
  }

  if (issues.length > 0) {
    return {
      state: 'invalid',
      label: 'Check link',
      detail: issues.join('; '),
      variant: 'outline',
    };
  }

  return {
    state: 'unchecked',
    label: 'Link ready',
    detail: sharepoint.storage_status || 'External link present, not verified yet',
    variant: 'secondary',
  };
}

function StatCard({ label, value, icon: Icon, tone = 'text-primary' }) {
  return (
    <Card className="border border-border">
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
          <Icon className={`w-4 h-4 ${tone}`} />
        </div>
        <p className="text-3xl font-black tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>{value}</p>
      </CardContent>
    </Card>
  );
}

export default function BCDocumentEventsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [recordType, setRecordType] = useState('Posted Sales Invoice');
  const [recordNo, setRecordNo] = useState('SAMPLE-INV-001');
  const [recordResult, setRecordResult] = useState(null);
  const [lastPostResult, setLastPostResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const refreshStatus = async () => {
    const res = await api.get('/bc-document-events/status');
    setStatus(res.data);
    return res.data;
  };

  const searchRecord = async () => {
    if (!recordType.trim() || !recordNo.trim()) {
      toast.error('Enter both BC record type and record number');
      return;
    }

    setWorking(true);
    try {
      const res = await api.get(`/bc-document-events/records/${encodeURIComponent(recordType.trim())}/${encodeURIComponent(recordNo.trim())}`);
      setRecordResult(res.data);
      toast.success(`Found ${res.data.document_count} document(s) and ${res.data.event_count} event(s)`);
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Record search failed');
    } finally {
      setWorking(false);
    }
  };

  const verifyLinks = async () => {
    if (!recordType.trim() || !recordNo.trim()) {
      toast.error('Enter both BC record type and record number');
      return;
    }

    setVerifying(true);
    try {
      const res = await api.post(`/bc-document-events/records/${encodeURIComponent(recordType.trim())}/${encodeURIComponent(recordNo.trim())}/verify-links`);
      toast.success(`Verified ${res.data.checked_count} link(s)`);
      await searchRecord();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Link verification failed');
    } finally {
      setVerifying(false);
    }
  };

  const handleLookupKeyDown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      searchRecord();
    }
  };

  const openDocument = (documentId) => {
    if (!documentId) return;
    navigate(`/documents/${documentId}`);
  };

  const repairOrphans = async () => {
    setWorking(true);
    try {
      const res = await api.post('/bc-document-events/repair-orphans');
      toast.success(`Repair checked ${res.data.checked_events} event(s), repaired ${res.data.repaired_documents} document(s)`);
      await refreshStatus();
      await searchRecord();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Repair failed');
    } finally {
      setWorking(false);
    }
  };

  const sendSampleEvent = async () => {
    setWorking(true);
    try {
      const res = await api.post('/bc-document-events/delivery-sent', SAMPLE_DELIVERY_EVENT);
      setLastPostResult(res.data);
      toast.success(res.data.duplicate ? 'Sample event was safely treated as duplicate' : 'Sample event recorded');
      await refreshStatus();
      await searchRecord();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Sample event failed');
    } finally {
      setWorking(false);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        await refreshStatus();
        const res = await api.get('/bc-document-events/records/Posted%20Sales%20Invoice/SAMPLE-INV-001');
        setRecordResult(res.data);
      } catch (err) {
        toast.error(err.response?.data?.detail || err.message || 'Failed to load BC document events');
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="bc-events-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto" data-testid="bc-document-events-page">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>BC Document Events</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Sandbox event bridge for future Business Central AL document delivery and attachment callbacks.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={refreshStatus} disabled={working || verifying} data-testid="refresh-bc-events-btn">
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
          <Button variant="secondary" onClick={repairOrphans} disabled={working || verifying} data-testid="repair-bc-events-btn">
            <Wrench className="w-4 h-4 mr-2" /> Repair Orphans
          </Button>
          <Button onClick={sendSampleEvent} disabled={working || verifying} data-testid="send-sample-bc-event-btn">
            <Send className="w-4 h-4 mr-2" /> Send Sample Event
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Events Recorded" value={status?.events_recorded ?? 0} icon={FileClock} tone="text-blue-500" />
        <StatCard label="Hub Documents" value={status?.bc_event_documents ?? 0} icon={CheckCircle2} tone="text-emerald-500" />
        <StatCard label="Orphan Events" value={status?.orphan_events ?? 0} icon={AlertCircle} tone={(status?.orphan_events ?? 0) > 0 ? 'text-red-500' : 'text-muted-foreground'} />
        <StatCard label="BC Writes" value={status?.writes_to_bc ? 'On' : 'Off'} icon={CheckCircle2} tone={status?.writes_to_bc ? 'text-red-500' : 'text-emerald-500'} />
      </div>

      <Card className="border border-border">
        <CardHeader>
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Lookup by BC Record</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto_auto] gap-3">
            <input
              value={recordType}
              onChange={(e) => setRecordType(e.target.value)}
              onKeyDown={handleLookupKeyDown}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              placeholder="BC record type, e.g. Posted Sales Invoice"
              data-testid="bc-record-type-input"
            />
            <input
              value={recordNo}
              onChange={(e) => setRecordNo(e.target.value)}
              onKeyDown={handleLookupKeyDown}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              placeholder="BC record number, e.g. 296152"
              data-testid="bc-record-no-input"
            />
            <Button onClick={searchRecord} disabled={working || verifying} data-testid="search-bc-record-btn">
              <Search className="w-4 h-4 mr-2" /> Search
            </Button>
            <Button variant="secondary" onClick={verifyLinks} disabled={working || verifying} data-testid="verify-bc-record-links-btn">
              <ShieldCheck className="w-4 h-4 mr-2" /> {verifying ? 'Verifying...' : 'Verify Links'}
            </Button>
          </div>
          {recordResult && (
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
              <div>
                <span className="text-muted-foreground">Current lookup:</span>{' '}
                <span className="font-medium">{recordResult.bc_record_type}</span>{' '}
                <span className="font-mono">{recordResult.bc_record_no}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{recordResult.document_count} document(s)</Badge>
                <Badge variant="secondary">{recordResult.event_count} event(s)</Badge>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {lastPostResult && (
        <Card className="border border-border">
          <CardHeader>
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Last Sample Event Result</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
              <div><span className="text-muted-foreground">Success:</span> <Badge variant={statusVariant(lastPostResult.success)}>{String(lastPostResult.success)}</Badge></div>
              <div><span className="text-muted-foreground">Duplicate:</span> <Badge variant={statusVariant(lastPostResult.duplicate)}>{String(lastPostResult.duplicate)}</Badge></div>
              <div><span className="text-muted-foreground">Event:</span> <span className="font-mono">{lastPostResult.event_id}</span></div>
              <div><span className="text-muted-foreground">Document:</span> <span className="font-mono break-all">{lastPostResult.document_id}</span></div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border border-border">
        <CardHeader>
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Linked Hub Documents</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Workflow</TableHead>
                <TableHead>BC Record</TableHead>
                <TableHead>Last Event</TableHead>
                <TableHead>Link Health</TableHead>
                <TableHead className="text-right">Open</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(recordResult?.documents || []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">No linked hub documents found.</TableCell>
                </TableRow>
              ) : (
                recordResult.documents.map((doc) => {
                  const linkHealth = getLinkHealth(doc);
                  return (
                    <TableRow
                      key={doc.id}
                      className="cursor-pointer hover:bg-muted/40"
                      onClick={() => openDocument(doc.id)}
                      data-testid={`bc-linked-document-row-${doc.id}`}
                    >
                      <TableCell>
                        <div className="font-medium">{doc.file_name || doc.document_no || doc.id}</div>
                        <div className="text-xs text-muted-foreground font-mono break-all">{doc.id}</div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{doc.doc_type || '-'}</Badge></TableCell>
                      <TableCell><Badge variant={statusVariant(doc.status)}>{doc.status || '-'}</Badge></TableCell>
                      <TableCell><Badge variant={statusVariant(doc.workflow_status)}>{doc.workflow_status || '-'}</Badge></TableCell>
                      <TableCell>
                        <div>{doc.bc_source?.record_type || '-'}</div>
                        <div className="text-xs text-muted-foreground font-mono">{doc.bc_source?.record_no || '-'}</div>
                      </TableCell>
                      <TableCell>
                        <div>{doc.last_bc_event_type || '-'}</div>
                        <div className="text-xs text-muted-foreground">{formatDate(doc.last_bc_event_utc)}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={linkHealth.variant}>{linkHealth.label}</Badge>
                        <div className="text-xs text-muted-foreground max-w-[260px] truncate" title={linkHealth.detail}>{linkHealth.detail}</div>
                        {linkHealth.checkedAt && <div className="text-[10px] text-muted-foreground">Checked {formatDate(linkHealth.checkedAt)}</div>}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(event) => {
                            event.stopPropagation();
                            openDocument(doc.id);
                          }}
                          data-testid={`open-bc-linked-document-${doc.id}`}
                        >
                          <ExternalLink className="w-4 h-4 mr-1.5" /> Open
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="border border-border">
        <CardHeader>
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Raw BC Events</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Received</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Delivery</TableHead>
                <TableHead>Correlation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(recordResult?.events || []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">No events found.</TableCell>
                </TableRow>
              ) : (
                recordResult.events.map((event) => (
                  <TableRow key={event.event_id}>
                    <TableCell className="font-mono text-xs break-all">{event.event_id}</TableCell>
                    <TableCell><Badge variant="outline">{event.event_type}</Badge></TableCell>
                    <TableCell>{formatDate(event.received_utc)}</TableCell>
                    <TableCell>{event.actor || '-'}</TableCell>
                    <TableCell>
                      <div>{event.payload?.delivery_status || event.payload?.storage_status || '-'}</div>
                      <div className="text-xs text-muted-foreground">{event.payload?.delivery_method || event.payload?.attachment_source || ''}</div>
                    </TableCell>
                    <TableCell className="font-mono text-xs break-all">{event.correlation_id || '-'}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
