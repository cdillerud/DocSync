import { useState, useEffect } from 'react';
import { 
  getJobTypes, updateJobType, getEmailWatcherConfig, updateEmailWatcherConfig,
  getEmailStats, classifyDocument,
  listMailboxSources, createMailboxSource, updateMailboxSource, deleteMailboxSource,
  testMailboxConnection, pollMailboxNow
} from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { Slider } from '../components/ui/slider';
import { Separator } from '../components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  Mail, FileText, Brain, Settings, RefreshCw, CheckCircle2, AlertCircle,
  Loader2, Save, Edit, Eye, Clock, TrendingUp, AlertTriangle, Zap,
  Plus, Trash2, Play, Plug, MailPlus
} from 'lucide-react';

const AUTOMATION_LEVELS = {
  0: { label: 'Manual Only', color: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200', description: 'Store and classify only' },
  1: { label: 'Auto Link', color: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200', description: 'Link to existing BC records' },
  2: { label: 'Auto Create Draft', color: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200', description: 'Create draft BC documents' },
  3: { label: 'Advanced', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200', description: 'Auto-populate lines' },
};

const JOB_TYPE_ICONS = {
  AP_Invoice: '📥',
  Sales_PO: '📦',
  AR_Invoice: '📤',
  Remittance: '💳',
  Freight_Document: '🚚',
  Warehouse_Document: '🏭',
  Sales_Order: '📋',
  Inventory_Report: '📊',
};

const CATEGORY_OPTIONS = [
  { value: 'AP', label: 'Accounts Payable', color: 'bg-blue-100 text-blue-800' },
  { value: 'Sales', label: 'Sales', color: 'bg-emerald-100 text-emerald-800' },
  { value: 'Operations', label: 'Operations', color: 'bg-purple-100 text-purple-800' },
  { value: 'HR', label: 'Human Resources', color: 'bg-amber-100 text-amber-800' },
  { value: 'Other', label: 'Other', color: 'bg-gray-100 text-gray-800' },
];

export default function EmailParserPage() {
  const [jobTypes, setJobTypes] = useState([]);
  const [emailConfig, setEmailConfig] = useState(null);
  const [emailStats, setEmailStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editingJob, setEditingJob] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [emailConfigForm, setEmailConfigForm] = useState({});
  const [savingEmail, setSavingEmail] = useState(false);
  
  // Mailbox sources state
  const [mailboxSources, setMailboxSources] = useState([]);
  const [showAddMailbox, setShowAddMailbox] = useState(false);
  const [editingMailbox, setEditingMailbox] = useState(null);
  const [mailboxForm, setMailboxForm] = useState({
    name: '',
    email_address: '',
    category: 'AP',
    enabled: true,
    polling_interval_minutes: 5,
    watch_folder: 'Inbox',
    needs_review_folder: 'Needs Review',
    processed_folder: 'Processed',
    description: ''
  });
  const [savingMailbox, setSavingMailbox] = useState(false);
  const [testingMailbox, setTestingMailbox] = useState(null);
  const [pollingMailbox, setPollingMailbox] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [jobRes, emailRes, statsRes, mailboxRes] = await Promise.all([
        getJobTypes(),
        getEmailWatcherConfig(),
        getEmailStats(),
        listMailboxSources()
      ]);
      setJobTypes(jobRes.data.job_types || []);
      setEmailConfig(emailRes.data);
      setEmailStats(statsRes.data);
      setMailboxSources(mailboxRes.data.mailbox_sources || []);
    } catch (err) {
      toast.error('Failed to load email parser settings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  // Mailbox source handlers
  const handleAddMailbox = () => {
    setEditingMailbox(null);
    setMailboxForm({
      name: '',
      email_address: '',
      category: 'AP',
      enabled: true,
      polling_interval_minutes: 5,
      watch_folder: 'Inbox',
      needs_review_folder: 'Needs Review',
      processed_folder: 'Processed',
      description: ''
    });
    setShowAddMailbox(true);
  };

  const handleEditMailbox = (mailbox) => {
    setEditingMailbox(mailbox);
    setMailboxForm({
      name: mailbox.name || '',
      email_address: mailbox.email_address || '',
      category: mailbox.category || 'AP',
      enabled: mailbox.enabled !== false,
      polling_interval_minutes: mailbox.polling_interval_minutes || 5,
      watch_folder: mailbox.watch_folder || 'Inbox',
      needs_review_folder: mailbox.needs_review_folder || 'Needs Review',
      processed_folder: mailbox.processed_folder || 'Processed',
      description: mailbox.description || ''
    });
    setShowAddMailbox(true);
  };

  const handleSaveMailbox = async () => {
    if (!mailboxForm.name || !mailboxForm.email_address) {
      toast.error('Name and email address are required');
      return;
    }
    
    setSavingMailbox(true);
    try {
      if (editingMailbox) {
        await updateMailboxSource(editingMailbox.mailbox_id, mailboxForm);
        toast.success('Mailbox updated');
      } else {
        await createMailboxSource(mailboxForm);
        toast.success('Mailbox added');
      }
      setShowAddMailbox(false);
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to save mailbox');
    } finally {
      setSavingMailbox(false);
    }
  };

  const handleDeleteMailbox = async (mailboxId) => {
    if (!window.confirm('Are you sure you want to delete this mailbox source?')) return;
    
    try {
      await deleteMailboxSource(mailboxId);
      toast.success('Mailbox deleted');
      fetchData();
    } catch (err) {
      toast.error('Failed to delete mailbox');
    }
  };

  const handleTestMailbox = async (mailboxId) => {
    setTestingMailbox(mailboxId);
    try {
      const res = await testMailboxConnection(mailboxId);
      if (res.data.status === 'success') {
        toast.success(`Connected! ${res.data.total_count} emails in inbox`);
      } else {
        toast.error(res.data.message || 'Connection failed');
      }
    } catch (err) {
      toast.error('Connection test failed');
    } finally {
      setTestingMailbox(null);
    }
  };

  const handlePollMailbox = async (mailboxId) => {
    setPollingMailbox(mailboxId);
    try {
      const res = await pollMailboxNow(mailboxId);
      toast.success(`Poll complete: ${res.data.attachments_ingested} documents ingested`);
    } catch (err) {
      toast.error('Poll failed');
    } finally {
      setPollingMailbox(null);
    }
  };

  const openEditDialog = (job) => {
    setEditingJob(job);
    setEditForm({
      automation_level: job.automation_level,
      min_confidence_to_auto_link: job.min_confidence_to_auto_link,
      min_confidence_to_auto_create_draft: job.min_confidence_to_auto_create_draft,
      requires_po_validation: job.requires_po_validation,
      requires_human_review_if_exception: job.requires_human_review_if_exception,
      enabled: job.enabled,
    });
  };

  const handleSaveJobType = async () => {
    setSaving(true);
    try {
      await updateJobType(editingJob.job_type, {
        ...editingJob,
        ...editForm,
      });
      toast.success(`${editingJob.display_name} updated`);
      setEditingJob(null);
      fetchData();
    } catch (err) {
      toast.error('Failed to save: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEmailConfig = async () => {
    setSavingEmail(true);
    try {
      await updateEmailWatcherConfig(emailConfigForm);
      toast.success('Email watcher configuration saved');
      fetchData();
    } catch (err) {
      toast.error('Failed to save: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSavingEmail(false);
    }
  };

  useEffect(() => {
    if (emailConfig) {
      setEmailConfigForm({
        mailbox_address: emailConfig.mailbox_address || '',
        watch_folder: emailConfig.watch_folder || 'Inbox',
        needs_review_folder: emailConfig.needs_review_folder || 'Needs Review',
        processed_folder: emailConfig.processed_folder || 'Processed',
        enabled: emailConfig.enabled || false,
        interval_minutes: emailConfig.interval_minutes || 5,
      });
    }
  }, [emailConfig]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="email-parser-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6" data-testid="email-parser-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Brain className="w-6 h-6 text-primary" />
            Email Parser Agent
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            AI-powered document classification and automation
          </p>
        </div>
        <Button variant="secondary" onClick={fetchData} data-testid="refresh-btn">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList data-testid="email-parser-tabs">
          <TabsTrigger value="overview" data-testid="tab-overview">
            <TrendingUp className="w-4 h-4 mr-2" /> Overview
          </TabsTrigger>
          <TabsTrigger value="job-types" data-testid="tab-job-types">
            <FileText className="w-4 h-4 mr-2" /> Job Types
          </TabsTrigger>
          <TabsTrigger value="email-config" data-testid="tab-email-config">
            <Mail className="w-4 h-4 mr-2" /> Email Watcher
          </TabsTrigger>
        </TabsList>

        {/* ==================== OVERVIEW TAB ==================== */}
        <TabsContent value="overview" className="space-y-4">
          {/* Stats Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4" data-testid="email-stats-grid">
            <Card className="border border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Mail className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold">{emailStats?.total_email_documents || 0}</p>
                    <p className="text-xs text-muted-foreground">Total Email Docs</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                    <AlertTriangle className="w-5 h-5 text-amber-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold">{emailStats?.needs_review || 0}</p>
                    <p className="text-xs text-muted-foreground">Needs Review</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                    <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold">{emailStats?.auto_linked || 0}</p>
                    <p className="text-xs text-muted-foreground">Auto Linked</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                    <Zap className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold">{emailConfig?.enabled ? 'Active' : 'Inactive'}</p>
                    <p className="text-xs text-muted-foreground">Watcher Status</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* By Job Type */}
          {emailStats?.by_job_type && Object.keys(emailStats.by_job_type).length > 0 && (
            <Card className="border border-border" data-testid="by-job-type-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Documents by Job Type
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(emailStats.by_job_type).map(([type, count]) => (
                    <div key={type} className="flex items-center gap-2 bg-muted/50 rounded-lg px-3 py-2">
                      <span className="text-lg">{JOB_TYPE_ICONS[type] || '📄'}</span>
                      <span className="font-medium">{type.replace('_', ' ')}</span>
                      <Badge variant="secondary">{count}</Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Recent Email Documents */}
          {emailStats?.recent && emailStats.recent.length > 0 && (
            <Card className="border border-border" data-testid="recent-emails-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Recent Email Documents
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {emailStats.recent.slice(0, 5).map((doc) => (
                    <div key={doc.id} className="flex items-center justify-between p-2 bg-muted/30 rounded-lg">
                      <div className="flex items-center gap-3">
                        <span className="text-lg">{JOB_TYPE_ICONS[doc.suggested_job_type] || '📄'}</span>
                        <div>
                          <p className="text-sm font-medium">{doc.file_name}</p>
                          <p className="text-xs text-muted-foreground">
                            {doc.email_sender} • {doc.suggested_job_type || 'Unclassified'}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {doc.ai_confidence && (
                          <Badge variant="outline" className="text-xs">
                            {(doc.ai_confidence * 100).toFixed(0)}% conf
                          </Badge>
                        )}
                        <Badge className={doc.status === 'NeedsReview' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}>
                          {doc.status}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ==================== JOB TYPES TAB ==================== */}
        <TabsContent value="job-types" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="job-types-grid">
            {jobTypes.map((job) => (
              <Card key={job.job_type} className="border border-border" data-testid={`job-type-${job.job_type}`}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{JOB_TYPE_ICONS[job.job_type] || '📄'}</span>
                      <div>
                        <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                          {job.display_name}
                        </CardTitle>
                        <CardDescription className="text-xs">{job.bc_entity}</CardDescription>
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => openEditDialog(job)} data-testid={`edit-${job.job_type}-btn`}>
                      <Edit className="w-4 h-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {/* Automation Level */}
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">Automation Level</span>
                    <Badge className={AUTOMATION_LEVELS[job.automation_level]?.color}>
                      {AUTOMATION_LEVELS[job.automation_level]?.label}
                    </Badge>
                  </div>

                  {/* Confidence Thresholds */}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Auto-Link Threshold</span>
                      <span className="font-mono">{(job.min_confidence_to_auto_link * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-emerald-500 rounded-full" 
                        style={{ width: `${job.min_confidence_to_auto_link * 100}%` }}
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Auto-Create Threshold</span>
                      <span className="font-mono">{(job.min_confidence_to_auto_create_draft * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-blue-500 rounded-full" 
                        style={{ width: `${job.min_confidence_to_auto_create_draft * 100}%` }}
                      />
                    </div>
                  </div>

                  {/* Validation Flags */}
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {job.requires_po_validation && (
                      <Badge variant="outline" className="text-xs">PO Validation</Badge>
                    )}
                    {job.requires_human_review_if_exception && (
                      <Badge variant="outline" className="text-xs">Review on Exception</Badge>
                    )}
                    {!job.enabled && (
                      <Badge variant="destructive" className="text-xs">Disabled</Badge>
                    )}
                  </div>

                  {/* Required Extractions */}
                  <div className="pt-1">
                    <p className="text-xs text-muted-foreground mb-1">Required Fields:</p>
                    <div className="flex flex-wrap gap-1">
                      {job.required_extractions?.map((field) => (
                        <Badge key={field} variant="secondary" className="text-xs font-mono">{field}</Badge>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* ==================== EMAIL CONFIG TAB ==================== */}
        <TabsContent value="email-config" className="space-y-4">
          {/* AP Mailbox Configuration */}
          <Card className="border border-border" data-testid="email-watcher-config-card">
            <CardHeader>
              <CardTitle className="text-base font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Mail className="w-5 h-5 text-blue-500" />
                AP Mailbox (Accounts Payable)
                <Badge variant="outline" className="ml-2 bg-blue-100 text-blue-800 border-blue-200">Primary</Badge>
              </CardTitle>
              <CardDescription>
                Monitor vendor invoices, remittances, and AP-related documents
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Enabled Toggle */}
              <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div>
                  <Label className="text-sm font-medium">AP Email Watcher Enabled</Label>
                  <p className="text-xs text-muted-foreground">
                    When enabled, the system will monitor this mailbox for AP documents
                  </p>
                </div>
                <Switch
                  checked={emailConfigForm.enabled}
                  onCheckedChange={(checked) => setEmailConfigForm(prev => ({ ...prev, enabled: checked }))}
                  data-testid="email-enabled-switch"
                />
              </div>

              <Separator />

              {/* Polling Interval */}
              <div className="space-y-2">
                <Label htmlFor="interval_minutes">Polling Interval (minutes)</Label>
                <div className="flex items-center gap-3">
                  <Input
                    id="interval_minutes"
                    type="number"
                    min="1"
                    max="60"
                    value={emailConfigForm.interval_minutes}
                    onChange={(e) => setEmailConfigForm(prev => ({ ...prev, interval_minutes: parseInt(e.target.value) || 5 }))}
                    className="w-24 font-mono"
                    data-testid="polling-interval-input"
                  />
                  <span className="text-sm text-muted-foreground">minutes between polls</span>
                </div>
              </div>

              <Separator />

              {/* Mailbox Address */}
              <div className="space-y-2">
                <Label htmlFor="mailbox_address">AP Mailbox Address</Label>
                <Input
                  id="mailbox_address"
                  placeholder="e.g. hub-ap-intake@yourcompany.com"
                  value={emailConfigForm.mailbox_address}
                  onChange={(e) => setEmailConfigForm(prev => ({ ...prev, mailbox_address: e.target.value }))}
                  className="font-mono"
                  data-testid="mailbox-address-input"
                />
              </div>

              {/* Folder Configuration */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="watch_folder">Watch Folder</Label>
                  <Input
                    id="watch_folder"
                    placeholder="Inbox"
                    value={emailConfigForm.watch_folder}
                    onChange={(e) => setEmailConfigForm(prev => ({ ...prev, watch_folder: e.target.value }))}
                    data-testid="watch-folder-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="needs_review_folder">Needs Review Folder</Label>
                  <Input
                    id="needs_review_folder"
                    placeholder="Needs Review"
                    value={emailConfigForm.needs_review_folder}
                    onChange={(e) => setEmailConfigForm(prev => ({ ...prev, needs_review_folder: e.target.value }))}
                    data-testid="needs-review-folder-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="processed_folder">Processed Folder</Label>
                  <Input
                    id="processed_folder"
                    placeholder="Processed"
                    value={emailConfigForm.processed_folder}
                    onChange={(e) => setEmailConfigForm(prev => ({ ...prev, processed_folder: e.target.value }))}
                    data-testid="processed-folder-input"
                  />
                </div>
              </div>

              {/* Save Button */}
              <div className="flex justify-end pt-2">
                <Button onClick={handleSaveEmailConfig} disabled={savingEmail} data-testid="save-email-config-btn">
                  {savingEmail ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="w-4 h-4 animate-spin" /> Saving...
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      <Save className="w-4 h-4" /> Save AP Configuration
                    </span>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Sales Mailbox Configuration */}
          <Card className="border border-border" data-testid="sales-email-config-card">
            <CardHeader>
              <CardTitle className="text-base font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Mail className="w-5 h-5 text-emerald-500" />
                Sales Mailbox
                <Badge variant="outline" className="ml-2 bg-emerald-100 text-emerald-800 border-emerald-200">Sales</Badge>
              </CardTitle>
              <CardDescription>
                Monitor customer POs, quotes, shipping requests, and sales-related documents
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="p-4 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-lg">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                      Environment Configuration Required
                    </p>
                    <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                      Sales mailbox is configured via environment variables on your server:
                    </p>
                    <code className="block text-xs mt-2 p-2 bg-amber-100 dark:bg-amber-900 rounded font-mono">
                      SALES_EMAIL_POLLING_ENABLED=true<br/>
                      SALES_EMAIL_POLLING_USER=hub-sales-intake@yourcompany.com
                    </code>
                    <p className="text-xs text-amber-700 dark:text-amber-300 mt-2">
                      Documents from both mailboxes will appear in the unified Document Queue with appropriate category tags.
                    </p>
                  </div>
                </div>
              </div>

              {/* Sales Email Status Info */}
              <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div>
                  <Label className="text-sm font-medium">Sales Email Status</Label>
                  <p className="text-xs text-muted-foreground">
                    Check your server's .env file for current configuration
                  </p>
                </div>
                <Badge variant="outline" className="text-xs">
                  Configured via .env
                </Badge>
              </div>
            </CardContent>
          </Card>

          {/* Current Status */}
          {emailConfig?.webhook_subscription_id && (
            <Card className="border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/30">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                  <div>
                    <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">
                      AP Webhook Active
                    </p>
                    <p className="text-xs text-emerald-700 dark:text-emerald-300">
                      Subscription ID: {emailConfig.webhook_subscription_id}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* ==================== EDIT JOB TYPE DIALOG ==================== */}
      <Dialog open={!!editingJob} onOpenChange={() => setEditingJob(null)}>
        <DialogContent className="max-w-md" data-testid="edit-job-type-dialog">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
              <span className="text-xl">{JOB_TYPE_ICONS[editingJob?.job_type]}</span>
              {editingJob?.display_name}
            </DialogTitle>
            <DialogDescription>
              Configure automation level and confidence thresholds
            </DialogDescription>
          </DialogHeader>

          {editingJob && (
            <div className="space-y-5 py-2">
              {/* Enabled Toggle */}
              <div className="flex items-center justify-between">
                <Label>Enabled</Label>
                <Switch
                  checked={editForm.enabled}
                  onCheckedChange={(checked) => setEditForm(prev => ({ ...prev, enabled: checked }))}
                  data-testid="job-enabled-switch"
                />
              </div>

              {/* Automation Level */}
              <div className="space-y-2">
                <Label>Automation Level</Label>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(AUTOMATION_LEVELS).map(([level, config]) => (
                    <button
                      key={level}
                      type="button"
                      className={`p-2 rounded-lg border text-left transition-colors ${
                        editForm.automation_level === parseInt(level)
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                      }`}
                      onClick={() => setEditForm(prev => ({ ...prev, automation_level: parseInt(level) }))}
                      data-testid={`automation-level-${level}`}
                    >
                      <Badge className={`${config.color} mb-1`}>{config.label}</Badge>
                      <p className="text-xs text-muted-foreground">{config.description}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Auto-Link Threshold */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Auto-Link Threshold</Label>
                  <span className="text-sm font-mono">{(editForm.min_confidence_to_auto_link * 100).toFixed(0)}%</span>
                </div>
                <Slider
                  value={[editForm.min_confidence_to_auto_link * 100]}
                  onValueChange={([val]) => setEditForm(prev => ({ ...prev, min_confidence_to_auto_link: val / 100 }))}
                  max={100}
                  step={5}
                  className="w-full"
                  data-testid="auto-link-slider"
                />
              </div>

              {/* Auto-Create Threshold */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Auto-Create Draft Threshold</Label>
                  <span className="text-sm font-mono">{(editForm.min_confidence_to_auto_create_draft * 100).toFixed(0)}%</span>
                </div>
                <Slider
                  value={[editForm.min_confidence_to_auto_create_draft * 100]}
                  onValueChange={([val]) => setEditForm(prev => ({ ...prev, min_confidence_to_auto_create_draft: val / 100 }))}
                  max={100}
                  step={5}
                  className="w-full"
                  data-testid="auto-create-slider"
                />
              </div>

              {/* Validation Options */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <Label>Require PO Validation</Label>
                    <p className="text-xs text-muted-foreground">Must match a PO in BC</p>
                  </div>
                  <Switch
                    checked={editForm.requires_po_validation}
                    onCheckedChange={(checked) => setEditForm(prev => ({ ...prev, requires_po_validation: checked }))}
                    data-testid="po-validation-switch"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <Label>Human Review on Exception</Label>
                    <p className="text-xs text-muted-foreground">Flag for review if validation fails</p>
                  </div>
                  <Switch
                    checked={editForm.requires_human_review_if_exception}
                    onCheckedChange={(checked) => setEditForm(prev => ({ ...prev, requires_human_review_if_exception: checked }))}
                    data-testid="review-exception-switch"
                  />
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="secondary" onClick={() => setEditingJob(null)}>Cancel</Button>
            <Button onClick={handleSaveJobType} disabled={saving} data-testid="save-job-type-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
