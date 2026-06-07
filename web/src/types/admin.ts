export interface RegisterForm {
  brand_name: string;
  contact_name: string;
  phone: string;
  email: string;
  password: string;
  verify_code: string;
}

export interface RegisterResponse {
  code: number;
  data?: {
    tenant_id: number;
    status: 'pending';
    message: string;
  };
  message?: string;
}

export interface ApprovalResponse {
  code: number;
  data?: {
    tenant_id: number;
    status: 'active';
    api_key: string;
    widget_snippet: string;
  };
  message?: string;
}

export interface TenantInfo {
  id: number;
  brand_name: string;
  contact_name: string;
  phone: string;
  email: string;
  status: 'pending' | 'active' | 'suspended' | 'rejected';
  api_key_hash: string;
  created_at: string;
  approved_at: string | null;
}

export interface AdminSessionFilter {
  tenant_id?: number;
  start_time?: string;
  end_time?: string;
}

export interface DashboardMetric {
  accuracy: number;
  conversion: number;
  retention: number;
  trust: number;
  history: { date: string; accuracy: number; conversion: number; retention: number; trust: number }[];
}
