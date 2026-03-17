import "@/App.css";
import "@/index.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import DocumentDetailPage from "@/pages/DocumentDetailPage";
import OperationsQueuePage from "@/pages/OperationsQueuePage";
import TemplatesPage from "@/pages/TemplatesPage";

// Hub pages (consolidated)
import DocumentsHubPage from "@/pages/DocumentsHubPage";
import VendorsHubPage from "@/pages/VendorsHubPage";
import SalesInventoryHubPage from "@/pages/SalesInventoryHubPage";
import IntelligenceHubPage from "@/pages/IntelligenceHubPage";
import IntegrationsHubPage from "@/pages/IntegrationsHubPage";
import SettingsHubPage from "@/pages/SettingsHubPage";

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="documents" element={<DocumentsHubPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="vendors" element={<VendorsHubPage />} />
        <Route path="sales-inventory" element={<SalesInventoryHubPage />} />
        <Route path="intelligence" element={<IntelligenceHubPage />} />
        <Route path="operations-queue" element={<OperationsQueuePage />} />
        <Route path="integrations" element={<IntegrationsHubPage />} />
        <Route path="config" element={<SettingsHubPage />} />
        <Route path="templates" element={<TemplatesPage />} />
        {/* Redirects for old URLs */}
        <Route path="queue" element={<Navigate to="/documents" replace />} />
        <Route path="upload" element={<Navigate to="/documents?tab=upload" replace />} />
        <Route path="file-import" element={<Navigate to="/documents?tab=import" replace />} />
        <Route path="vendor-intelligence" element={<Navigate to="/vendors" replace />} />
        <Route path="stable-vendors" element={<Navigate to="/vendors?tab=stable" replace />} />
        <Route path="sales-orders" element={<Navigate to="/sales-inventory" replace />} />
        <Route path="inventory-ledger" element={<Navigate to="/sales-inventory?tab=inventory" replace />} />
        <Route path="document-review" element={<Navigate to="/intelligence" replace />} />
        <Route path="document-bundles" element={<Navigate to="/intelligence?tab=bundles" replace />} />
        <Route path="document-lifecycle" element={<Navigate to="/intelligence?tab=lifecycle" replace />} />
        <Route path="label-correction-insights" element={<Navigate to="/intelligence?tab=labels" replace />} />
        <Route path="layout-fingerprints" element={<Navigate to="/intelligence?tab=layouts" replace />} />
        <Route path="sharepoint-routing" element={<Navigate to="/integrations" replace />} />
        <Route path="bc-integration" element={<Navigate to="/integrations?tab=bc" replace />} />
        <Route path="email-parser" element={<Navigate to="/config?tab=email" replace />} />
        <Route path="settings" element={<Navigate to="/config" replace />} />
        <Route path="automation-rules" element={<Navigate to="/config?tab=automation" replace />} />
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
