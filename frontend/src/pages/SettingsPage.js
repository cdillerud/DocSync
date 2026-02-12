import { useState, useEffect } from 'react';
import { getSettingsStatus } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { toast } from 'sonner';
import { RefreshCw, CheckCircle2, AlertCircle, Database, Cloud, Building2, Shield } from 'lucide-react';

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

export default function SettingsPage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="settings-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  const connections = [
    {
      key: 'mongodb',
      icon: Database,
      title: 'MongoDB',
      description: 'Document & workflow persistence',
      data: status?.connections?.mongodb,
      details: [{ label: 'Status', value: status?.connections?.mongodb?.detail }],
    },
    {
      key: 'sharepoint',
      icon: Cloud,
      title: 'SharePoint Online',
      description: 'Document storage via Microsoft Graph',
      data: status?.connections?.sharepoint,
      details: [
        { label: 'Site', value: status?.connections?.sharepoint?.site },
        { label: 'Path', value: status?.connections?.sharepoint?.path },
        { label: 'Library', value: status?.connections?.sharepoint?.library },
      ],
    },
    {
      key: 'business_central',
      icon: Building2,
      title: 'Business Central',
      description: 'ERP record linking via BC API v2.0',
      data: status?.connections?.business_central,
      details: [
        { label: 'Environment', value: status?.connections?.business_central?.environment },
        { label: 'Company', value: status?.connections?.business_central?.company },
      ],
    },
    {
      key: 'entra_id',
      icon: Shield,
      title: 'Entra ID (Azure AD)',
      description: 'Service-to-service authentication',
      data: status?.connections?.entra_id,
      details: [
        { label: 'Tenant', value: status?.connections?.entra_id?.tenant_id },
      ],
    },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="settings-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Settings</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Connection status and configuration</p>
        </div>
        <Button variant="secondary" onClick={fetchStatus} data-testid="settings-refresh-btn">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Demo Mode Notice */}
      {status?.demo_mode && (
        <Card className="border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30" data-testid="settings-demo-notice">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">Demo Mode Active</p>
                <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                  All Microsoft API calls are simulated. To connect live services, configure the environment
                  variables below and set <code className="font-mono bg-amber-200/50 dark:bg-amber-800/50 px-1 rounded">DEMO_MODE=false</code>.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Connection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="connection-cards">
        {connections.map(({ key, icon: Icon, title, description, data, details }) => (
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

      {/* Environment Variables Reference */}
      <Card className="border border-border" data-testid="env-vars-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Required Environment Variables</CardTitle>
          <CardDescription>Configure these in your .env file to connect live services</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="bg-muted rounded-lg p-4 font-mono text-xs space-y-1 overflow-x-auto">
            <p className="text-muted-foreground"># Entra ID / Azure AD</p>
            <p>TENANT_ID=&lt;your-tenant-id&gt;</p>
            <p>&nbsp;</p>
            <p className="text-muted-foreground"># Business Central</p>
            <p>BC_ENVIRONMENT=Sandbox</p>
            <p>BC_COMPANY_NAME=CRONUS USA, Inc.</p>
            <p>BC_CLIENT_ID=&lt;app-registration-client-id&gt;</p>
            <p>BC_CLIENT_SECRET=&lt;app-registration-secret&gt;</p>
            <p>&nbsp;</p>
            <p className="text-muted-foreground"># Microsoft Graph (SharePoint)</p>
            <p>GRAPH_CLIENT_ID=&lt;graph-app-client-id&gt;</p>
            <p>GRAPH_CLIENT_SECRET=&lt;graph-app-secret&gt;</p>
            <p>SHAREPOINT_SITE_HOSTNAME=yourcompany.sharepoint.com</p>
            <p>SHAREPOINT_SITE_PATH=/sites/GPI-DocumentHub-Test</p>
            <p>SHAREPOINT_LIBRARY_NAME=Documents</p>
            <p>&nbsp;</p>
            <p className="text-muted-foreground"># Hub Config</p>
            <p>DEMO_MODE=false</p>
          </div>
        </CardContent>
      </Card>

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
    </div>
  );
}
