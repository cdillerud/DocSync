import "@/App.css";
import "@/index.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import UploadPage from "@/pages/UploadPage";
import QueuePage from "@/pages/QueuePage";
import DocumentDetailPage from "@/pages/DocumentDetailPage";
import SettingsPage from "@/pages/SettingsPage";
import EmailParserPage from "@/pages/EmailParserPage";
import AuditDashboardPage from "@/pages/AuditDashboardPage";
import SalesDashboardPage from "@/pages/SalesDashboardPage";
import WorkflowQueuesPage from "@/pages/WorkflowQueuesPage";

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
        <Route path="upload" element={<UploadPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="email-parser" element={<EmailParserPage />} />
        <Route path="audit" element={<AuditDashboardPage />} />
        <Route path="sales" element={<SalesDashboardPage />} />
        <Route path="settings" element={<SettingsPage />} />
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
