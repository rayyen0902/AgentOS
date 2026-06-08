import { useState, FormEvent, useEffect } from 'react';
import { RegisterForm } from '../types/admin';

interface Props {
  onSuccess: (tenantId: number) => void;
}

export function RegisterPage({ onSuccess }: Props) {
  const [form, setForm] = useState<RegisterForm>({
    brand_name: '',
    contact_name: '',
    phone: '',
    email: '',
    password: '',
    verify_code: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (codeCooldown > 0) {
      const t = setTimeout(() => setCodeCooldown((c) => c - 1), 1000);
      return () => clearTimeout(t);
    }
  }, [codeCooldown]);

  const handleChange = (field: keyof RegisterForm) => (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
    setError(null);
  };

  const sendCode = async () => {
    if (!form.phone) {
      setError('请先输入手机号');
      return;
    }
    if (codeCooldown > 0) return;

    setSendingCode(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/auth/send-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: form.phone }),
      });
      const data = await res.json();
      if (data.code === 0) {
        setCodeCooldown(60);
      } else {
        setError(data.message || '验证码发送失败');
      }
    } catch {
      setError('网络错误，请重试');
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;

    const { brand_name, contact_name, phone, email, password, verify_code } = form;
    if (!brand_name || !contact_name || !phone || !email || !password || !verify_code) {
      setError('请填写所有字段');
      return;
    }

    // Phone validation: must be digits
    if (!/^\d+$/.test(phone)) {
      setError('手机号必须为纯数字');
      return;
    }
    if (phone.length !== 11) {
      setError('手机号必须为11位');
      return;
    }

    // Password validation: PRD 8-32 chars, uppercase + lowercase + digit
    if (password.length < 8 || password.length > 32) {
      setError('密码长度需为 8-32 位');
      return;
    }
    if (!/[A-Z]/.test(password)) {
      setError('密码需包含大写字母');
      return;
    }
    if (!/[a-z]/.test(password)) {
      setError('密码需包含小写字母');
      return;
    }
    if (!/[0-9]/.test(password)) {
      setError('密码需包含数字');
      return;
    }

    if (verify_code.length !== 6 || !/^\d{6}$/.test(verify_code)) {
      setError('验证码为 6 位数字');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.code === 0 && data.data) {
        onSuccess(data.data.tenant_id);
      } else {
        setError(data.message || '注册失败，请重试');
      }
    } catch {
      setError('网络错误，请检查连接');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="register-page">
      <div className="register-card">
        <h2>品牌方注册</h2>
        <p className="register-subtitle">注册后需等待管理员审批</p>

        {error && (
          <div className="register-error">
            <span>{error}</span>
            <button onClick={() => setError(null)}>×</button>
          </div>
        )}

        <form className="register-form" onSubmit={handleSubmit}>
          <label>
            品牌名称
            <input
              type="text"
              value={form.brand_name}
              onChange={handleChange('brand_name')}
              placeholder="输入品牌名称"
              required
            />
          </label>
          <label>
            联系人
            <input
              type="text"
              value={form.contact_name}
              onChange={handleChange('contact_name')}
              placeholder="输入联系人姓名"
              required
            />
          </label>
          <label>
            手机号
            <input
              type="tel"
              value={form.phone}
              onChange={handleChange('phone')}
              placeholder="输入手机号"
              maxLength={11}
              required
            />
          </label>
          <label>
            邮箱
            <input
              type="email"
              value={form.email}
              onChange={handleChange('email')}
              placeholder="输入邮箱地址"
              required
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={form.password}
              onChange={handleChange('password')}
              placeholder="8-32位，需含大小写字母和数字"
              minLength={8}
              required
            />
          </label>
          <label className="verify-code-row">
            验证码
            <div className="verify-code-group">
              <input
                type="text"
                value={form.verify_code}
                onChange={handleChange('verify_code')}
                placeholder="6位数字"
                maxLength={6}
                required
              />
              <button
                type="button"
                className="send-code-btn"
                onClick={sendCode}
                disabled={sendingCode || codeCooldown > 0}
              >
                {sendingCode
                  ? '发送中...'
                  : codeCooldown > 0
                  ? `${codeCooldown}s 后重发`
                  : '发送验证码'}
              </button>
            </div>
          </label>
          <button
            type="submit"
            className="register-submit-btn"
            disabled={submitting}
          >
            {submitting ? '提交中...' : '提交注册'}
          </button>
        </form>
      </div>
    </div>
  );
}
