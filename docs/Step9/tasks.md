# Step 9 消项清单

> 你负责：前端卡片组件 + 租户注册审批 + B 端管理后台 + PWA + widget.js

---

## #6 【Critical】PWA sw.js 含 TypeScript 类型标注，注册失败

**文件**: `web/public/sw.js:4,22,50`

**问题**: `.js` 文件里写了 `event: ExtendableEvent` 等 TS 语法，浏览器报 SyntaxError。

**修复**: 
1. 删除所有类型标注（`event: ExtendableEvent` → `event`）
2. 或改用 `vite-plugin-pwa` 自动生成 SW（推荐）
3. `main.tsx` 加 `updatefound` 事件监听，提示用户刷新

---

## #9 【Critical】ApprovalPage 无 tenant_id + admin API 全部缺 auth

**文件**: 
- `web/src/pages/ApprovalPage.tsx`
- `web/src/admin/AdminTenants.tsx`
- `web/src/admin/AdminDashboard.tsx`
- `web/src/admin/AdminSessions.tsx`
- `web/src/admin/AdminKnowledge.tsx`
- `web/src/admin/AdminPlatforms.tsx`

**修复**:
1. `App.tsx` 把 `tenant_id` 作为 prop/query param 传给 `ApprovalPage`
2. `ApprovalPage` 加轮询（每 30s GET 审批状态）
3. **所有 admin API 调用加 `X-Admin-Key` header**（从环境变量或登录态获取）

---

## #22 【High】前端: 两套中断 UI + CardRenderer as any + admin 密钥泄露 + price bug

| 文件 | 问题 | 修复 |
|------|------|------|
| `cards/InterruptCard.tsx` ↔ `InterruptPanel.tsx` | options 类型不同 `{label,value}[]` vs `string[]` | 统一为 `{label, value}[]` |
| `cards/CardRenderer.tsx:19-30` | 全部 `as any` | 用 `CardDataMap` 类型守卫 |
| `admin/AdminTenants.tsx:44` | API Key 用 `alert()` 不可复制 | 改为 modal + copy 按钮 |
| `admin/AdminKnowledge.tsx:74` | `price \|\| ''` 吞 0 | 改为 `price ?? ''` 或显式 `price !== undefined ? price : ''` |
| `admin/AdminPlatforms.tsx` | Type 缺 secret/token 字段 | 补 `app_secret`/`token`/`encoding_aes_key` 字段 |
| `admin/AdminDashboard.tsx` | 无自动刷新 | 加 30s 轮询或 SSE 订阅 |

---

## #23 部分归属 Step 9【High】widget.js 404

**文件**: `web/public/widget.js`

**修复**:
1. 在 `App.tsx` 加 `/widget?tenant_id=:id` 路由 → 独立 ChatContainer
2. widget.js 域名从 hardcode `hufu.cn` 改为从 script tag `data-api-base` 属性读取

---

## #27 部分归属 Step 9【Medium】卡片组件问题

| 文件 | 问题 | 修复 |
|------|------|------|
| `cards/WorkshopCard.tsx:20` | `/product/:id` 路由不存在 | 改为 `#` 或实现产品详情路由 |
| `cards/InterruptCard.tsx:25` | timer 父组件 re-render 重置 | 用 `useRef` 存 timer，只在 data 变更时重启 |
| `cards/InterruptCard.tsx` | 缺 `session_id` / `interrupt_id` | InterruptCardData 补字段 |

---

## 关联：低优先级

- `manifest.json` 补 `purpose: "any maskable"`、`categories`、`screenshots`
- `sw.js` 缓存策略从 network-first 改为 stale-while-revalidate
- Admin 页面 A11y: `AdminKnowledge` tabs 加 `role="tab"` `aria-selected` `aria-controls`
- widget.js iframe 加 `sandbox` 属性
- RegisterPage 密码规则对齐 PRD: 8-32位 + 大小写 + 数字
