import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from 'next-themes';
import { Button } from '../components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator
} from '../components/ui/dropdown-menu';
import {
  LayoutDashboard, UploadCloud, Files, Settings, Moon, Sun, LogOut, Menu, X, Brain, FileSpreadsheet, ChevronRight, FolderSync
} from 'lucide-react';
import { useState, useEffect } from 'react';

const API = process.env.REACT_APP_BACKEND_URL;

// Simplified navigation - removed redundant workflow pages
const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', exact: true },
  { to: '/upload', icon: UploadCloud, label: 'Upload' },
  { to: '/queue', icon: Files, label: 'Document Queue' },
  { to: '/file-import', icon: FileSpreadsheet, label: 'File Import' },
  { to: '/email-parser', icon: Brain, label: 'Email Config' },
  { to: '/migration/onegamer-poc', icon: FolderSync, label: 'SP Migration POC' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bcStatus, setBcStatus] = useState({ loading: true, connected: false, demoMode: false, environment: '' });

  // Fetch BC sandbox status on mount
  useEffect(() => {
    const fetchBCStatus = async () => {
      try {
        // Try the BC status endpoint first
        const res = await fetch(`${API}/api/bc-sandbox/status`);
        if (res.ok) {
          const data = await res.json();
          // Determine connection status based on config
          const hasCredentials = data.config?.has_secret === true;
          const isNotDemoMode = data.demo_mode === false;
          const isConnected = isNotDemoMode && hasCredentials;
          
          console.log('[BC Status]', { 
            demo_mode: data.demo_mode, 
            has_secret: data.config?.has_secret,
            environment: data.config?.environment,
            computed_connected: isConnected 
          });
          
          setBcStatus({
            loading: false,
            connected: isConnected,
            demoMode: data.demo_mode === true,
            environment: data.config?.environment || 'Unknown'
          });
        } else {
          // If BC status fails, try settings endpoint as fallback
          console.warn('[BC Status] Primary endpoint failed:', res.status, '- trying settings fallback');
          try {
            const settingsRes = await fetch(`${API}/api/settings`);
            if (settingsRes.ok) {
              const settings = await settingsRes.json();
              const bcConfig = settings.bc_sandbox || {};
              const hasSecret = bcConfig.client_secret_set || bcConfig.has_secret;
              setBcStatus({
                loading: false,
                connected: hasSecret === true,
                demoMode: !hasSecret,
                environment: bcConfig.environment || 'Configured'
              });
              console.log('[BC Status] Using settings fallback:', bcConfig);
            } else {
              setBcStatus({ loading: false, connected: false, demoMode: true, environment: '' });
            }
          } catch (fallbackErr) {
            console.warn('[BC Status] Settings fallback also failed:', fallbackErr);
            setBcStatus({ loading: false, connected: false, demoMode: true, environment: '' });
          }
        }
      } catch (err) {
        console.error('[BC Status] Fetch failed:', err.message);
        // On network error, show neutral state instead of error
        setBcStatus({ loading: false, connected: false, demoMode: true, environment: '' });
      }
    };
    fetchBCStatus();
  }, []);

  const getPageTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Dashboard';
    if (path === '/upload') return 'Upload Document';
    if (path === '/queue') return 'Document Queue';
    if (path === '/file-import') return 'File Import';
    if (path.startsWith('/documents/')) return 'Document Detail';
    if (path === '/email-parser') return 'Email Config';
    if (path === '/settings') return 'Settings';
    return 'GPI Document Hub';
  };

  return (
    <div className="flex h-screen overflow-hidden" data-testid="main-layout">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        className={`glass-sidebar fixed md:static inset-y-0 left-0 z-50 w-64 border-r border-border flex flex-col transform transition-transform duration-200 md:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}
        data-testid="sidebar"
      >
        <div className="h-16 flex items-center gap-3 px-5 border-b border-border shrink-0">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-primary-foreground font-black text-sm" style={{ fontFamily: 'Chivo, sans-serif' }}>G</span>
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>GPI Document Hub</h1>
            <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-medium">Phase 1 POC</p>
          </div>
          <button className="md:hidden ml-auto p-1" onClick={() => setSidebarOpen(false)} data-testid="close-sidebar-btn">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto" data-testid="sidebar-nav">
          {navItems.map(({ to, icon: Icon, label, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-primary/10 text-primary border-l-2 border-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                }`
              }
              data-testid={`nav-${label.toLowerCase().replace(/\s+/g, '-')}`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-border shrink-0">
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground" data-testid="bc-status-indicator">
            {bcStatus.loading ? (
              <>
                <div className="w-2 h-2 rounded-full bg-gray-400 animate-pulse" />
                <span className="font-mono">CHECKING...</span>
              </>
            ) : bcStatus.connected ? (
              <>
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="font-mono text-emerald-600 dark:text-emerald-400">BC SANDBOX</span>
              </>
            ) : (
              <>
                <div className="w-2 h-2 rounded-full bg-amber-500" />
                <span className="font-mono text-amber-600 dark:text-amber-400">
                  {bcStatus.demoMode ? 'DEMO MODE' : 'BC STANDBY'}
                </span>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-16 bg-background/80 backdrop-blur-md border-b border-border/50 sticky top-0 z-30 flex items-center justify-between px-4 md:px-6 shrink-0" data-testid="header">
          <div className="flex items-center gap-3">
            <button className="md:hidden p-2 hover:bg-accent rounded-md" onClick={() => setSidebarOpen(true)} data-testid="open-sidebar-btn">
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="hidden sm:inline">GPI Hub</span>
              <ChevronRight className="w-3 h-3 hidden sm:inline" />
              <span className="font-semibold text-foreground">{getPageTitle()}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              data-testid="theme-toggle-btn"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="h-9 gap-2 px-3" data-testid="user-menu-btn">
                  <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center">
                    <span className="text-xs font-bold text-primary">
                      {user?.display_name?.charAt(0) || 'A'}
                    </span>
                  </div>
                  <span className="hidden sm:inline text-sm">{user?.display_name || 'Admin'}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <div className="px-2 py-1.5">
                  <p className="text-sm font-medium">{user?.display_name}</p>
                  <p className="text-xs text-muted-foreground">{user?.role}</p>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} data-testid="logout-btn">
                  <LogOut className="w-4 h-4 mr-2" />
                  Log out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8" data-testid="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
