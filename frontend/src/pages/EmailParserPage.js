import { useState, useEffect } from 'react';
import { 
  getJobTypes, updateJobType, getEmailWatcherConfig, updateEmailWatcherConfig,
  getEmailStats, classifyDocument,
  listMailboxSources, createMailboxSource, updateMailboxSource, deleteMailboxSource,
  testMailboxConnection, pollMailboxNow, getMailboxPollingStatus
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
  const [pollingStatus, setPollingStatus] = useState(null);
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
          {/* Header with Add Button */}
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold">Mailbox Sources</h3>
              <p className="text-sm text-muted-foreground">
                Configure email mailboxes to monitor for incoming documents
              </p>
            </div>
            <Button onClick={handleAddMailbox} data-testid="add-mailbox-btn">
              <Plus className="w-4 h-4 mr-2" />
              Add Mailbox
            </Button>
          </div>

          {/* Mailbox Sources List */}
          {mailboxSources.length === 0 ? (
            <Card className="border border-dashed">
              <CardContent className="p-8 text-center">
                <MailPlus className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                <h4 className="font-medium mb-2">No mailboxes configured</h4>
                <p className="text-sm text-muted-foreground mb-4">
                  Add your first mailbox source to start ingesting documents automatically
                </p>
                <Button onClick={handleAddMailbox} variant="outline">
                  <Plus className="w-4 h-4 mr-2" />
                  Add Your First Mailbox
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {mailboxSources.map((mailbox) => {
                const categoryConfig = CATEGORY_OPTIONS.find(c => c.value === mailbox.category) || CATEGORY_OPTIONS[4];
                return (
                  <Card key={mailbox.mailbox_id} className="border">
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex items-start gap-3 min-w-0 flex-1">
                          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${mailbox.enabled ? 'bg-primary/10' : 'bg-muted'}`}>
                            <Mail className={`w-5 h-5 ${mailbox.enabled ? 'text-primary' : 'text-muted-foreground'}`} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h4 className="font-medium">{mailbox.name}</h4>
                              <Badge variant="outline" className={`text-xs ${categoryConfig.color}`}>
                                {categoryConfig.label}
                              </Badge>
                              {!mailbox.enabled && (
                                <Badge variant="secondary" className="text-xs">Disabled</Badge>
                              )}
                            </div>
                            <p className="text-sm text-muted-foreground font-mono truncate">
                              {mailbox.email_address}
                            </p>
                            {mailbox.description && (
                              <p className="text-xs text-muted-foreground mt-1">{mailbox.description}</p>
                            )}
                            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                Every {mailbox.polling_interval_minutes} min
                              </span>
                              <span>Watch: {mailbox.watch_folder}</span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleTestMailbox(mailbox.mailbox_id)}
                            disabled={testingMailbox === mailbox.mailbox_id}
                            title="Test Connection"
                          >
                            {testingMailbox === mailbox.mailbox_id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Plug className="w-4 h-4" />
                            )}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handlePollMailbox(mailbox.mailbox_id)}
                            disabled={pollingMailbox === mailbox.mailbox_id}
                            title="Poll Now"
                          >
                            {pollingMailbox === mailbox.mailbox_id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Play className="w-4 h-4" />
                            )}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleEditMailbox(mailbox)}
                            title="Edit"
                          >
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDeleteMailbox(mailbox.mailbox_id)}
                            className="text-destructive hover:text-destructive"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}

          {/* Info Card */}
          <Card className="border border-dashed border-muted-foreground/30 bg-muted/20">
            <CardContent className="p-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <Brain className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-sm">Unified Document Pipeline</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Documents from all mailboxes are ingested into a single queue. The AI classifier automatically 
                    determines the document type and category. Use the Document Queue to view and manage all documents.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ==================== ADD/EDIT MAILBOX DIALOG ==================== */}
      <Dialog open={showAddMailbox} onOpenChange={setShowAddMailbox}>
        <DialogContent className="max-w-lg" data-testid="mailbox-dialog">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold flex items-center gap-2">
              <Mail className="w-5 h-5" />
              {editingMailbox ? 'Edit Mailbox Source' : 'Add Mailbox Source'}
            </DialogTitle>
            <DialogDescription>
              Configure a mailbox to monitor for incoming documents
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Name */}
            <div className="space-y-2">
              <Label htmlFor="mailbox-name">Display Name *</Label>
              <Input
                id="mailbox-name"
                placeholder="e.g. AP Invoices, Sales Orders"
                value={mailboxForm.name}
                onChange={(e) => setMailboxForm(prev => ({ ...prev, name: e.target.value }))}
                data-testid="mailbox-name-input"
              />
            </div>

            {/* Email Address */}
            <div className="space-y-2">
              <Label htmlFor="mailbox-email">Email Address *</Label>
              <Input
                id="mailbox-email"
                placeholder="e.g. hub-ap-intake@yourcompany.com"
                value={mailboxForm.email_address}
                onChange={(e) => setMailboxForm(prev => ({ ...prev, email_address: e.target.value }))}
                className="font-mono"
                data-testid="mailbox-email-input"
              />
            </div>

            {/* Category */}
            <div className="space-y-2">
              <Label>Default Category</Label>
              <Select
                value={mailboxForm.category}
                onValueChange={(val) => setMailboxForm(prev => ({ ...prev, category: val }))}
              >
                <SelectTrigger data-testid="mailbox-category-select">
                  <SelectValue placeholder="Select category" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((cat) => (
                    <SelectItem key={cat.value} value={cat.value}>
                      <span className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${cat.color.split(' ')[0]}`} />
                        {cat.label}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                AI will override this based on document content
              </p>
            </div>

            {/* Enabled + Interval Row */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Switch
                  checked={mailboxForm.enabled}
                  onCheckedChange={(checked) => setMailboxForm(prev => ({ ...prev, enabled: checked }))}
                  data-testid="mailbox-enabled-switch"
                />
                <Label>Enabled</Label>
              </div>
              <div className="flex items-center gap-2 flex-1">
                <Label className="whitespace-nowrap">Poll every</Label>
                <Input
                  type="number"
                  min="1"
                  max="60"
                  value={mailboxForm.polling_interval_minutes}
                  onChange={(e) => setMailboxForm(prev => ({ ...prev, polling_interval_minutes: parseInt(e.target.value) || 5 }))}
                  className="w-20 font-mono"
                />
                <span className="text-sm text-muted-foreground">min</span>
              </div>
            </div>

            {/* Folders */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Watch Folder</Label>
                <Input
                  placeholder="Inbox"
                  value={mailboxForm.watch_folder}
                  onChange={(e) => setMailboxForm(prev => ({ ...prev, watch_folder: e.target.value }))}
                  className="text-sm"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Review Folder</Label>
                <Input
                  placeholder="Needs Review"
                  value={mailboxForm.needs_review_folder}
                  onChange={(e) => setMailboxForm(prev => ({ ...prev, needs_review_folder: e.target.value }))}
                  className="text-sm"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Processed Folder</Label>
                <Input
                  placeholder="Processed"
                  value={mailboxForm.processed_folder}
                  onChange={(e) => setMailboxForm(prev => ({ ...prev, processed_folder: e.target.value }))}
                  className="text-sm"
                />
              </div>
            </div>

            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="mailbox-desc">Description (optional)</Label>
              <Input
                id="mailbox-desc"
                placeholder="e.g. Main AP inbox for vendor invoices"
                value={mailboxForm.description}
                onChange={(e) => setMailboxForm(prev => ({ ...prev, description: e.target.value }))}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddMailbox(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveMailbox} disabled={savingMailbox} data-testid="save-mailbox-btn">
              {savingMailbox ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 className="w-4 h-4 animate-spin" /> Saving...
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <Save className="w-4 h-4" /> {editingMailbox ? 'Update' : 'Add'} Mailbox
                </span>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
