import { NavLink, Outlet } from 'react-router-dom';

const NAV_ITEMS = [
  { to: '/admin/tenants', label: '租户管理' },
  { to: '/admin/dashboard', label: '评价看板' },
  { to: '/admin/sessions', label: '会话日志' },
  { to: '/admin/platforms', label: '平台配置' },
  { to: '/admin/knowledge', label: '知识管理' },
];

export function AdminLayout() {
  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-header">
          <h3>管理后台</h3>
        </div>
        <nav className="admin-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `admin-nav-link ${isActive ? 'active' : ''}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  );
}
