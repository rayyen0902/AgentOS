import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import './App.css';
import { ChatContainer } from './components/ChatContainer';
import { RegisterPage } from './pages/RegisterPage';
import { ApprovalPage } from './pages/ApprovalPage';
import { AdminLayout } from './admin/AdminLayout';
import { AdminTenants } from './admin/AdminTenants';
import { AdminDashboard } from './admin/AdminDashboard';
import { AdminSessions } from './admin/AdminSessions';
import { AdminPlatforms } from './admin/AdminPlatforms';
import { AdminKnowledge } from './admin/AdminKnowledge';
import { useCallback } from 'react';

function RegisterWithRedirect() {
  const navigate = useNavigate();

  const handleSuccess = useCallback(
    (tenantId: number) => {
      navigate(`/approval?tenant_id=${tenantId}`, { replace: true });
    },
    [navigate]
  );

  return <RegisterPage onSuccess={handleSuccess} />;
}

function WidgetPage() {
  const tenantId = new URLSearchParams(window.location.search).get('tenant_id');
  if (!tenantId) {
    return <p>Error: tenant_id is required</p>;
  }
  // Widget iframe page — minimal chat interface for embedding
  return <ChatContainer widgetMode tenantId={tenantId} />;
}

function App() {
  const basename = import.meta.env.BASE_URL?.replace(/\/+$/, '') || '/';
  return (
    <BrowserRouter basename={basename}>
      <Routes>
        <Route path="/" element={<ChatContainer />} />
        <Route path="/register" element={<RegisterWithRedirect />} />
        <Route path="/approval" element={<ApprovalPage />} />
        <Route path="/widget" element={<WidgetPage />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="tenants" element={<AdminTenants />} />
          <Route path="dashboard" element={<AdminDashboard />} />
          <Route path="sessions" element={<AdminSessions />} />
          <Route path="platforms" element={<AdminPlatforms />} />
          <Route path="knowledge" element={<AdminKnowledge />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
