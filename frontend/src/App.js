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

// Hub pages (consolidated)
import DocumentsHubPage from "@/pages/DocumentsHubPage";
import SalesInventoryHubPage from "@/pages/SalesInventoryHubPage";
import SalespersonDashboardPage from "@/pages/SalespersonDashboardPage";
import IntelligenceHubPage from "@/pages/IntelligenceHubPage";
import IntegrationsHubPage from "@/pages/IntegrationsHubPage";
import SettingsHubPage from "@/pages/SettingsHubPage";
import BakeOffPage from "@/pages/BakeOffPage";
import SalesOrderReviewPage from "@/pages/SalesOrderReviewPage";

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
        <Route index element={<DocumentsHubPage />} />
        <Route path="documents" element={<DocumentsHubPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="review/:id" element={<SalesOrderReviewPage />} />
        <Route path="sales-inventory" element={<SalesInventoryHubPage />} />
        <Route path="config" element={<SettingsHubPage />} />
        {/* Keep old pages accessible but not in nav */}
        <Route path="intelligence" element={<IntelligenceHubPage />} />
        <Route path="operations-queue" element={<OperationsQueuePage />} />
        <Route path="integrations" element={<IntegrationsHubPage />} />
        <Route path="intake-benchmark" element={<BakeOffPage />} />
        {/* Redirects */}
        <Route path="queue" element={<Navigate to="/" replace />} />
        <Route path="upload" element={<Navigate to="/?tab=upload" replace />} />
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
