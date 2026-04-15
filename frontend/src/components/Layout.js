import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from 'next-themes';
import { Button } from '../components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator
} from '../components/ui/dropdown-menu';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger
} from '../components/ui/dialog';
import { ScrollArea } from '../components/ui/scroll-area';
import { Badge } from '../components/ui/badge';
import {
  LayoutDashboard, Files, Settings, Moon, Sun, LogOut, Menu, X, ChevronRight, ShoppingCart, ClipboardList, Brain, FolderTree, ArrowLeftRight, Sparkles, Tag, Wrench, Bug, FlaskConical, TrendingUp, ClipboardCheck, Activity, Shield, Map
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { APP_VERSION, CHANGELOG } from '../lib/version';

const API = process.env.REACT_APP_BACKEND_URL;

// Core navigation — daily workflows + key modules
const navItems = [
  { to: '/', icon: Files, label: 'Inbox', exact: true },
  { to: '/monitor', icon: Activity, label: 'Monitor' },
  { to: '/governance', icon: Shield, label: 'Governance' },
  { to: '/sales-inventory', icon: ShoppingCart, label: 'Sales' },
  { to: '/posting-intelligence', icon: Brain, label: 'Posting AI' },
  { to: '/invoice-trace', icon: ArrowLeftRight, label: 'Trace' },
  { to: '/ai-learning', icon: TrendingUp, label: 'AI Learning' },
  { to: '/review-queue', icon: ClipboardCheck, label: 'Review Queue' },
  { to: '/insights', icon: TrendingUp, label: 'Insights' },
  { to: '/roadmap', icon: Map, label: 'Roadmap' },
  { to: '/config', icon: Settings, label: 'Settings' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bcStatus, setBcStatus] = useState({ loading: true, connected: false, demoMode: false, readEnv: '', writeEnv: '' });
  const [reviewBadge, setReviewBadge] = useState(0);

  // Fetch review queue badge count
  useEffect(() => {
    const fetchBadge = async () => {
      try {
        const res = await fetch(`${API}/api/posting-patterns/review-queue/badge-count`);
        if (res.ok) {
          const data = await res.json();
          setReviewBadge(data.count || 0);
        }
      } catch { /* ignore */ }
    };
    fetchBadge();
    const interval = setInterval(fetchBadge, 60000); // Poll every 60s
    return () => clearInterval(interval);
  }, []);

  // Fetch BC status on mount
  useEffect(() => {
    const fetchBCStatus = async () => {
      try {
        const [res, envRes] = await Promise.all([
          fetch(`${API}/api/bc-sandbox/status`),
          fetch(`${API}/api/bc/environment-status`).catch(() => null),
        ]);
        if (res.ok) {
          const data = await res.json();
          const envData = envRes?.ok ? await envRes.json() : null;
          const hasCredentials = data.config?.has_secret === true;
          const isNotDemoMode = data.demo_mode === false;
          const isConnected = isNotDemoMode && hasCredentials;
          
          setBcStatus({
            loading: false,
            connected: isConnected,
            demoMode: data.demo_mode === true,
            readEnv: envData?.read_environment || 'Unknown',
            writeEnv: envData?.write_environment || 'Unknown',
            blockProdWrites: envData?.block_production_writes ?? true,
          });
        } else {
          setBcStatus({ loading: false, connected: false, demoMode: true, readEnv: '', writeEnv: '' });
        }
      } catch (err) {
        console.error('[BC Status] Fetch failed:', err.message);
        setBcStatus({ loading: false, connected: false, demoMode: true, readEnv: '', writeEnv: '' });
      }
    };
    fetchBCStatus();
  }, []);

  const getPageTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Inbox';
    if (path === '/documents') return 'Inbox';
    if (path === '/sales-inventory') return 'Sales';
    if (path === '/insights') return 'Insights';
    if (path === '/posting-intelligence') return 'Posting Intelligence';
    if (path === '/invoice-trace') return 'Invoice Trace';
    if (path === '/ai-learning') return 'AI Learning Intelligence';
    if (path === '/monitor') return 'System Monitor';
    if (path === '/governance') return 'Governance';
    if (path === '/roadmap') return 'Build Roadmap';
    if (path === '/review-queue') return 'Draft Review Queue';
    if (path === '/config') return 'Settings';
    if (path.startsWith('/documents/')) return 'Document Detail';
    if (path.startsWith('/review/')) return 'Sales Order Review';
    return 'GPI Hub';
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
              {label === 'Review Queue' && reviewBadge > 0 && (
                <span className="ml-auto bg-amber-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1" data-testid="review-badge">
                  {reviewBadge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-border shrink-0">
          <div className="px-3 py-2 text-xs text-muted-foreground space-y-1" data-testid="bc-status-indicator">
            {bcStatus.loading ? (
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-gray-400 animate-pulse" />
                <span className="font-mono">CHECKING...</span>
              </div>
            ) : bcStatus.connected ? (
              <>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="font-mono text-emerald-600 dark:text-emerald-400">BC CONNECTED</span>
                </div>
                <div className="flex items-center gap-2 pl-4" data-testid="bc-read-env">
                  <span className="font-mono text-[10px] text-blue-600 dark:text-blue-400">READ</span>
                  <span className="font-mono text-[10px]">{bcStatus.readEnv}</span>
                </div>
                <div className="flex items-center gap-2 pl-4" data-testid="bc-write-env">
                  <span className="font-mono text-[10px] text-amber-600 dark:text-amber-400">WRITE</span>
                  <span className="font-mono text-[10px]">{bcStatus.writeEnv}</span>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-amber-500" />
                <span className="font-mono text-amber-600 dark:text-amber-400">
                  {bcStatus.demoMode ? 'DEMO MODE' : 'BC STANDBY'}
                </span>
              </div>
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
            {/* Version badge with changelog */}
            <Dialog>
              <DialogTrigger asChild>
                <button
                  className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 hover:bg-primary/20 transition-colors cursor-pointer"
                  data-testid="version-badge"
                >
                  <Tag className="w-3 h-3 text-primary" />
                  <span className="text-xs font-mono font-semibold text-primary">v{APP_VERSION}</span>
                </button>
              </DialogTrigger>
              <DialogContent className="max-w-lg max-h-[80vh]" data-testid="changelog-dialog">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2 text-lg" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    <Sparkles className="w-5 h-5 text-primary" />
                    What's New
                  </DialogTitle>
                </DialogHeader>
                <ScrollArea className="h-[60vh] pr-4">
                  <div className="space-y-6">
                    {CHANGELOG.map((release) => (
                      <div key={release.version} className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="font-mono text-xs">v{release.version}</Badge>
                          <span className="text-xs text-muted-foreground">{release.date}</span>
                        </div>
                        <h3 className="text-sm font-semibold">{release.title}</h3>
                        <ul className="space-y-1.5">
                          {release.changes.map((change, i) => {
                            const iconMap = { feature: Sparkles, improvement: Wrench, fix: Bug };
                            const colorMap = { feature: 'text-emerald-500', improvement: 'text-blue-500', fix: 'text-amber-500' };
                            const ChangeIcon = iconMap[change.type] || Sparkles;
                            return (
                              <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                                <ChangeIcon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${colorMap[change.type] || 'text-muted-foreground'}`} />
                                <span>{change.text}</span>
                              </li>
                            );
                          })}
                        </ul>
                        {release.version !== CHANGELOG[CHANGELOG.length - 1].version && (
                          <div className="border-b border-border/50 pt-2" />
                        )}
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </DialogContent>
            </Dialog>

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
