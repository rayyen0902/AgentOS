import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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
import { useState } from 'react';

function App() {
  const [registeredTenantId, setRegisteredTenantId] = useState<number | null>(null);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatContainer />} />
        <Route
          path="/register"
          element={
            registeredTenantId ? (
              <ApprovalPage />
            ) : (
              <RegisterPage onSuccess={(id) => setRegisteredTenantId(id)} />
            )
          }
        />
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
