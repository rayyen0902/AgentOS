# Step 9 消项清单

> 负责：前端卡片组件 + 租户注册审批 + B 端管理后台 + PWA + widget.js
> GitHub Issue: #6, #9, #22, #23(部分), #27(部分)

---

## 🔴 Critical — #6, #9 (4 条)

- [ ] **S9-01** `web/public/sw.js:4,22,50` — `.js` 文件含 TypeScript 类型标注 (`event: ExtendableEvent` 等)，浏览器报 SyntaxError，SW 注册失败。删除所有类型标注，或改用 `vite-plugin-pwa` 自动生成
- [ ] **S9-02** `web/src/pages/ApprovalPage.tsx` — `App.tsx` 不给它传 `tenant_id` prop，审批页无法查询状态。加 prop 或 query param
- [ ] **S9-03** `web/src/pages/ApprovalPage.tsx` — 无轮询机制检测审批通过。加 30s 间隔 GET
- [ ] **S9-04** `web/src/admin/` 全部 6 个文件 — 所有 admin API 调用缺 `X-Admin-Key` header。PRD 19.2 规定必需

---

## 🟠 High — #22, #23(部分) (6 条)

- [ ] **S9-05** `web/src/cards/InterruptCard.tsx` vs `web/src/components/InterruptPanel.tsx` — options 类型不兼容：`string[]` vs `{label:string, value:string}[]`。统一为 `{label, value}[]`
- [ ] **S9-06** `web/src/cards/CardRenderer.tsx:19-30` — 全部 `card.data as any` 绕过 TypeScript。改为用 `CardDataMap` 类型守卫
- [ ] **S9-07** `web/src/admin/AdminTenants.tsx:44` — API Key 用 `alert()` 弹窗，不可复制。PRD 说 API Key 只返回一次。改为 modal + copy 按钮
- [ ] **S9-08** `web/src/admin/AdminKnowledge.tsx:74` — `price || ''` 吞掉 price=0（免费产品）。改为 `price ?? ''`
- [ ] **S9-09** `web/src/admin/AdminPlatforms.tsx` — `PlatformConfig` Type 缺 `app_secret`/`token`/`encoding_aes_key` 字段。补全字段
- [ ] **S9-10** `web/public/widget.js` — iframe URL `baseUrl + '/widget?tenant_id=...'` 但 React 路由表无 `/widget` 路由。加路由或在 App.tsx 处理

---

## 🟡 Medium (7 条)

- [ ] **S9-11** `web/src/cards/WorkshopCard.tsx:20` — 产品链接跳 `/product/:id` 但路由不存在。改为 `#` 或实现详情路由
- [ ] **S9-12** `web/src/cards/InterruptCard.tsx:25` — timer `useEffect` 在父组件 re-render 时重置。用 `useRef` 存 timer
- [ ] **S9-13** `web/src/cards/InterruptCard.tsx` — `InterruptCardData` 缺 `session_id` / `interrupt_id` 字段
- [ ] **S9-14** `web/src/cards/WorkshopCard.tsx` — `<img>` 无 `onError` 处理，图片加载失败显示破碎图标
- [ ] **S9-15** `web/src/admin/AdminDashboard.tsx` — 无自动刷新。加 30s 轮询或 SSE
- [ ] **S9-16** `web/src/admin/AdminKnowledge.tsx` — 产品和冲突规则无分页。大量数据时 DOM 堆积
- [ ] **S9-17** `web/src/admin/AdminSessions.tsx:42-72` — `tenant_id` filter 输入 `Number()` 可能产生 NaN

---

## 🟢 Low (13 条)

- [ ] **S9-18** `web/public/sw.js:30-44` — 缓存策略是 network-first 而非 stale-while-revalidate。cache 写了但很少读
- [ ] **S9-19** `web/public/sw.js` — `CACHE_NAME` 硬编码 `agentos-v0.3`，每次部署需手动改。改用 hash 或 `vite-plugin-pwa`
- [ ] **S9-20** `web/src/main.tsx` — SW 注册后不监听 `updatefound`/`statechange`，用户收不到新版本通知
- [ ] **S9-21** `web/public/manifest.json` — 缺 `"purpose": "any maskable"` 在 icon 条目上
- [ ] **S9-22** `web/public/manifest.json` — `"orientation": "portrait-primary"` 限制横屏。改为 `"portrait"` 或删除
- [ ] **S9-23** `web/public/widget.js` — 无 `sandbox` 属性在 iframe 上
- [ ] **S9-24** `web/public/widget.js` — CSS `position: fixed` 可能与宿主页面 fixed 元素冲突
- [ ] **S9-25** `web/public/widget.js` — 域名 hardcode `hufu.cn` 与 `api.hufu.cn` 不一致。改从 script tag `data-api-base` 属性读
- [ ] **S9-26** `web/src/pages/RegisterPage.tsx` — 密码规则与 PRD 不符。前端 `minLength=6`，PRD 要求 8-32 位 + 大小写 + 数字
- [ ] **S9-27** `web/src/pages/RegisterPage.tsx` — 手机号无格式校验。`maxLength={11}` 但不管是否全数字
- [ ] **S9-28** `web/src/admin/AdminKnowledge.tsx` — tabs 缺 WAI-ARIA: `role="tab"` `aria-selected` `aria-controls` `role="tabpanel"`
- [ ] **S9-29** `web/src/admin/AdminTenants.tsx` — `handleApprove` 发空 body，`handleReject` 发 `{action:"reject"}`。不一致
- [ ] **S9-30** `web/package.json` — `react-router-dom ^7.17.0` 可能与代码中 v6 API 风格不兼容。降级或迁移
- [ ] **S9-31** `web/vite.config.ts` — 无 `base` 路径配置。子路径部署时资源路径断裂
- [ ] **S9-32** `web/tsconfig.json` — `noUnusedLocals`/`noUnusedParameters` 启用但代码中有未用变量，`tsc` 编译可能失败
