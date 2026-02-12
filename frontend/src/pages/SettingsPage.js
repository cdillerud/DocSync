import { useState, useEffect } from 'react';
import { getSettingsStatus, getSettingsConfig, updateSettingsConfig, testConnection } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { Separator } from '../components/ui/separator';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  RefreshCw, CheckCircle2, AlertCircle, Database, Cloud,
  Building2, Shield, Settings, Pencil, Eye, EyeOff, Loader2,
  Zap, Save, RotateCcw
} from 'lucide-react';

const STATUS_ICON = {
  connected: <CheckCircle2 className="w-5 h-5 text-emerald-500" />,
  configured: <CheckCircle2 className="w-5 h-5 text-emerald-500" />,
  demo: <AlertCircle className="w-5 h-5 text-amber-500" />,
  not_configured: <AlertCircle className="w-5 h-5 text-red-500" />,
};

const STATUS_BADGE = {
  connected: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300',
  configured: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300',
  demo: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300',
  not_configured: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
};

const CONFIG_SECTIONS = [
  {
    title: 'Entra ID / Azure AD',
    icon: Shield,
    description: 'Tenant used for service-to-service auth with BC and Graph',
    fields: [
      { key: 'TENANT_ID', label: 'Tenant ID', placeholder: 'e.g. xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', secret: false },
    ],
  },
  {
    title: 'Business Central',
    icon: Building2,
    description: 'Entra App registration with BC API permissions',
    fields: [
      { key: 'BC_ENVIRONMENT', label: 'Environment', placeholder: 'e.g. Sandbox', secret: false },
      { key: 'BC_COMPANY_NAME', label: 'Company Name', placeholder: 'e.g. CRONUS USA, Inc.', secret: false },
      { key: 'BC_CLIENT_ID', label: 'Client ID', placeholder: 'App registration client ID', secret: false },
      { key: 'BC_CLIENT_SECRET', label: 'Client Secret', placeholder: 'App registration secret', secret: true },
    ],
  },
  {
    title: 'Microsoft Graph (SharePoint)',
    icon: Cloud,
    description: 'Entra App registration with Sites.ReadWrite.All or equivalent',
    fields: [
      { key: 'GRAPH_CLIENT_ID', label: 'Client ID', placeholder: 'Graph app client ID', secret: false },
      { key: 'GRAPH_CLIENT_SECRET', label: 'Client Secret', placeholder: 'Graph app secret', secret: true },
      { key: 'SHAREPOINT_SITE_HOSTNAME', label: 'Site Hostname', placeholder: 'e.g. yourcompany.sharepoint.com', secret: false },
      { key: 'SHAREPOINT_SITE_PATH', label: 'Site Path', placeholder: 'e.g. /sites/GPI-DocumentHub-Test', secret: false },
      { key: 'SHAREPOINT_LIBRARY_NAME', label: 'Library Name', placeholder: 'e.g. Documents', secret: false },
    ],
  },
];

export default function SettingsPage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [configForm, setConfigForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [showSecrets, setShowSecrets] = useState({});
  const [testing, setTesting] = useState({});

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await getSettingsStatus();
      setStatus(res.data);
    } catch (err) {
      toast.error('Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  const openConfigDialog = async () => {
    try {
      const res = await getSettingsConfig();
      setConfigForm(res.data.config || {});
      setShowSecrets({});
      setDialogOpen(true);
    } catch (err) {
      toast.error('Failed to load configuration');
    }
  };

  const handleFieldChange = (key, value) => {
    setConfigForm(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await updateSettingsConfig(configForm);
      toast.success(res.data.message || 'Configuration saved');
      setDialogOpen(false);
      fetchStatus();
    } catch (err) {
      toast.error('Failed to save: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async (service) => {
    setTesting(prev => ({ ...prev, [service]: true }));
    try {
      const res = await testConnection(service);
      const d = res.data;
      if (d.status === 'ok') {
        toast.success(`${service.toUpperCase()}: ${d.detail}`);
      } else if (d.status === 'demo') {
        toast.info(`${service.toUpperCase()}: ${d.detail}`);
      } else {
        toast.error(`${service.toUpperCase()}: ${d.detail}`);
      }
    } catch (err) {
      toast.error(`Test failed: ${err.message}`);
    } finally {
      setTesting(prev => ({ ...prev, [service]: false }));
    }
  };

  const toggleSecret = (key) => {
    setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="settings-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  const connections = [
    {
      key: 'mongodb', icon: Database, title: 'MongoDB',
      description: 'Document & workflow persistence',
      data: status?.connections?.mongodb,
      details: [{ label: 'Status', value: status?.connections?.mongodb?.detail }],
      testKey: null,
    },
    {
      key: 'sharepoint', icon: Cloud, title: 'SharePoint Online',
      description: 'Document storage via Microsoft Graph',
      data: status?.connections?.sharepoint,
      details: [
        { label: 'Site', value: status?.connections?.sharepoint?.site },
        { label: 'Path', value: status?.connections?.sharepoint?.path },
        { label: 'Library', value: status?.connections?.sharepoint?.library },
      ],
      testKey: 'graph',
    },
    {
      key: 'business_central', icon: Building2, title: 'Business Central',
      description: 'ERP record linking via BC API v2.0',
      data: status?.connections?.business_central,
      details: [
        { label: 'Environment', value: status?.connections?.business_central?.environment },
        { label: 'Company', value: status?.connections?.business_central?.company },
      ],
      testKey: 'bc',
    },
    {
      key: 'entra_id', icon: Shield, title: 'Entra ID (Azure AD)',
      description: 'Service-to-service authentication',
      data: status?.connections?.entra_id,
      details: [
        { label: 'Tenant', value: status?.connections?.entra_id?.tenant_id },
      ],
      testKey: null,
    },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="settings-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Settings</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Connection status and configuration</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={fetchStatus} data-testid="settings-refresh-btn">
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
          <Button onClick={openConfigDialog} data-testid="configure-credentials-btn">
            <Pencil className="w-4 h-4 mr-2" /> Configure Credentials
          </Button>
        </div>
      </div>

      {/* Demo Mode Notice */}
      {status?.demo_mode && (
        <Card className="border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30" data-testid="settings-demo-notice">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">Demo Mode Active</p>
                <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                  All Microsoft API calls are simulated. Click <strong>Configure Credentials</strong> to enter your Entra ID, BC, and SharePoint settings.
                </p>
              </div>
              <Button size="sm" variant="outline" className="shrink-0 border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900" onClick={openConfigDialog} data-testid="demo-configure-btn">
                <Settings className="w-3.5 h-3.5 mr-1.5" /> Configure
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Connection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="connection-cards">
        {connections.map(({ key, icon: Icon, title, description, data, details, testKey }) => (
          <Card key={key} className="border border-border" data-testid={`connection-${key}`}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center">
                    <Icon className="w-5 h-5 text-muted-foreground" />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>{title}</CardTitle>
                    <CardDescription className="text-xs">{description}</CardDescription>
                  </div>
                </div>
                {STATUS_ICON[data?.status]}
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2 mb-3">
                <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_BADGE[data?.status] || ''}`}>
                  {data?.status?.replace('_', ' ').toUpperCase()}
                </span>
                {testKey && (
                  <Button
                    variant="ghost" size="sm" className="h-6 text-xs ml-auto"
                    onClick={() => handleTestConnection(testKey)}
                    disabled={testing[testKey]}
                    data-testid={`test-${testKey}-btn`}
                  >
                    {testing[testKey] ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Zap className="w-3 h-3 mr-1" />}
                    Test
                  </Button>
                )}
              </div>
              <div className="space-y-2">
                {details.map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-mono text-foreground">{value || 'Not set'}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* SharePoint Folders */}
      {status?.sharepoint_folders && (
        <Card className="border border-border" data-testid="sp-folders-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>SharePoint Folder Structure</CardTitle>
            <CardDescription>Documents are organized into these folders by type</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {status.sharepoint_folders.map((folder) => (
                <Badge key={folder} variant="secondary" className="text-xs font-mono">{folder}/</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ==================== CONFIG DIALOG ==================== */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="config-dialog">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              <Settings className="w-5 h-5 inline mr-2 text-primary" />
              Configure Environment Credentials
            </DialogTitle>
            <DialogDescription>
              Enter your Entra ID, Business Central, and SharePoint credentials. Secrets are masked when displayed.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-2">
            {CONFIG_SECTIONS.map(({ title, icon: SectionIcon, description, fields }) => (
              <div key={title} data-testid={`config-section-${title.toLowerCase().replace(/[^a-z]/g, '-')}`}>
                <div className="flex items-center gap-2.5 mb-3">
                  <div className="w-8 h-8 rounded-md bg-primary/10 flex items-center justify-center">
                    <SectionIcon className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>{title}</h3>
                    <p className="text-xs text-muted-foreground">{description}</p>
                  </div>
                </div>

                <div className="space-y-3 ml-10">
                  {fields.map(({ key, label, placeholder, secret }) => (
                    <div key={key} className="space-y-1.5">
                      <Label htmlFor={key} className="text-xs font-medium">{label}</Label>
                      <div className="relative">
                        <Input
                          id={key}
                          type={secret && !showSecrets[key] ? 'password' : 'text'}
                          value={configForm[key] || ''}
                          onChange={(e) => handleFieldChange(key, e.target.value)}
                          placeholder={placeholder}
                          className="h-9 text-sm font-mono pr-10"
                          data-testid={`config-input-${key}`}
                        />
                        {secret && (
                          <button
                            type="button"
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                            onClick={() => toggleSecret(key)}
                            data-testid={`toggle-secret-${key}`}
                          >
                            {showSecrets[key] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <Separator className="mt-4" />
              </div>
            ))}

            {/* Demo Mode Toggle */}
            <div className="flex items-center justify-between ml-10" data-testid="demo-mode-toggle-section">
              <div>
                <Label className="text-sm font-medium">Demo Mode</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  When on, all Microsoft APIs are simulated with mock data
                </p>
              </div>
              <Switch
                checked={configForm.DEMO_MODE === 'true'}
                onCheckedChange={(checked) => handleFieldChange('DEMO_MODE', checked ? 'true' : 'false')}
                data-testid="demo-mode-switch"
              />
            </div>
          </div>

          <DialogFooter className="flex-col sm:flex-row gap-2 pt-4 border-t border-border">
            <p className="text-xs text-muted-foreground flex-1">
              Changes are saved to the backend <code className="font-mono bg-muted px-1 rounded">.env</code> file and take effect immediately.
            </p>
            <div className="flex gap-2 shrink-0">
              <Button variant="secondary" onClick={() => setDialogOpen(false)} data-testid="config-cancel-btn">
                <RotateCcw className="w-3.5 h-3.5 mr-1.5" /> Cancel
              </Button>
              <Button onClick={handleSave} disabled={saving} data-testid="config-save-btn">
                {saving ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <Save className="w-3.5 h-3.5" /> Save Configuration
                  </span>
                )}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
