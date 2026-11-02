import "@/App.css";
import "@/index.css";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";
const DocumentDetailPage = lazy(() => import("@/pages/DocumentDetailPage"));
const HumanDecisionQueuePage = lazy(() => import("@/pages/HumanDecisionQueuePage"));
const SearchPage = lazy(() => import("@/pages/SearchPage"));
const OperationsQueuePage = lazy(() => import("@/pages/OperationsQueuePage"));

// Hub pages (consolidated)
const SalesInventoryHubPage = lazy(() => import("@/pages/SalesInventoryHubPage"));
const IntakeLearningPage = lazy(() => import("@/pages/IntakeLearningPage"));
const IntelligenceHubPage = lazy(() => import("@/pages/IntelligenceHubPage"));
const APWorkflowPage = lazy(() => import("@/pages/APWorkflowPage"));
const APTestingPage = lazy(() => import("@/pages/APTestingPage"));
import SalesInboxPage from "@/pages/SalesInboxPage";
import TodayPage from "@/pages/TodayPage";
import APInboxPage from "@/pages/APInboxPage";
const IntegrationsHubPage = lazy(() => import("@/pages/IntegrationsHubPage"));
const SettingsHubPage = lazy(() => import("@/pages/SettingsHubPage"));
const BakeOffPage = lazy(() => import("@/pages/BakeOffPage"));
const UploadPage = lazy(() => import("@/pages/UploadPage"));
const PostingPatternsDashboard = lazy(() => import("@/pages/PostingPatternsDashboard"));
const InvoiceTracePage = lazy(() => import("@/pages/InvoiceTracePage"));
const ReviewQueuePage = lazy(() => import("@/pages/ReviewQueuePage"));
const Square9ReadinessPage = lazy(() => import("@/pages/Square9ReadinessPage"));

// Settings, legacy and rarely used pages load on first visit, not with every
// sign-in: the bundle carried about 41k lines of pages up front.
function page(Component) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <Component />
    </Suspense>
  );
}

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

// The old sales review page approved straight into BC, beside the Hub's own
// sales drafting: its links (legacy queues) open the document page instead.
function RedirectToDoc() {
  const { id } = useParams();
  return <Navigate to={`/documents/${encodeURIComponent(id)}`} replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<TodayPage />} />
        <Route path="documents" element={<Navigate to="/search" replace />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="review/:id" element={<RedirectToDoc />} />
        <Route path="sales-inventory" element={page(SalesInventoryHubPage)} />
        <Route path="intake/learning" element={page(IntakeLearningPage)} />
        <Route path="config" element={page(SettingsHubPage)} />
        {/* Keep old pages accessible but not in nav */}
        <Route path="intelligence" element={page(IntelligenceHubPage)} />
        <Route path="operations-queue" element={page(OperationsQueuePage)} />
        <Route path="integrations" element={page(IntegrationsHubPage)} />
        <Route path="posting-intelligence" element={page(PostingPatternsDashboard)} />
        <Route path="invoice-trace" element={page(InvoiceTracePage)} />
        <Route path="monitor" element={<Navigate to="/" replace />} />
        <Route path="square9-readiness" element={page(Square9ReadinessPage)} />
        <Route path="decision-queue" element={<HumanDecisionQueuePage />} />
        <Route path="ap-workflow" element={page(APWorkflowPage)} />
        <Route path="ap-testing" element={page(APTestingPage)} />
        <Route path="sales" element={<SalesInboxPage />} />
        <Route path="ap" element={<APInboxPage />} />
        <Route path="review-queue" element={page(ReviewQueuePage)} />
        <Route path="intake-benchmark" element={page(BakeOffPage)} />
        {/* Redirects */}
        <Route path="queue" element={<Navigate to="/" replace />} />
        <Route path="upload" element={page(UploadPage)} />
        <Route path="dashboard" element={<Navigate to="/" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
          <Toaster position="bottom-right" />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
