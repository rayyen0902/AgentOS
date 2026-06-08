# Step 9 消项清单

> 负责：前端卡片组件 + 租户注册审批 + B 端管理后台 + PWA + widget.js
> GitHub Issue: #6, #9, #22, #23(部分), #27(部分)

---

## 🔴 Critical — #6, #9 (4 条)

- [x] **S9-01** `web/public/sw.js:4,22,50` — `.js` 文件含 TypeScript 类型标注 (`event: ExtendableEvent` 等)，浏览器报 SyntaxError，SW 注册失败。删除所有类型标注，或改用 `vite-plugin-pwa` 自动生成 → fixed: 已改为纯 JS 无类型注解，CACHE_NAME 用 Date.now() 动态生成
- [x] **S9-02** `web/src/pages/ApprovalPage.tsx` — `App.tsx` 不给它传 `tenant_id` prop，审批页无法查询状态。加 prop 或 query param → fixed: 已用 useSearchParams().get('tenant_id') 从 URL query param 读取
- [x] **S9-03** `web/src/pages/ApprovalPage.tsx` — 无轮询机制检测审批通过。加 30s 间隔 GET → fixed: 已加 POLL_INTERVAL=30000，setInterval 轮询 checkStatus，立即首次检查，active 后清 timer
- [x] **S9-04** `web/src/admin/` 全部 6 个文件 — 所有 admin API 调用缺 `X-Admin-Key` header。PRD 19.2 规定必需 → fixed: adminFetch() 统一注入 X-Admin-Key header，所有 6 个 admin 文件已通过该函数调用

---

## 🟠 High — #22, #23(部分) (6 条)

- [x] **S9-05** `web/src/cards/InterruptCard.tsx` vs `web/src/components/InterruptPanel.tsx` — options 类型不兼容：`string[]` vs `{label:string, value:string}[]`。统一为 `{label, value}[]` → fixed: types/sse.ts 中 InterruptOption 为 {label,value}[]，interrupt card data 中 options 同类型，InterruptPanel 中 interrupt.options.map(opt => opt.value/opt.label)
- [x] **S9-06** `web/src/cards/CardRenderer.tsx:19-30` — 全部 `card.data as any` 绕过 TypeScript。改为用 `CardDataMap` 类型守卫 → fixed: CardRenderer 中 card 入参为 TypedCard union type（workshop|skin_report|interrupt|schedule），各 case 分支中 data 已精确推导为对应卡片数据类型
- [x] **S9-07** `web/src/admin/AdminTenants.tsx:44` — API Key 用 `alert()` 弹窗，不可复制。PRD 说 API Key 只返回一次。改为 modal + copy 按钮 → fixed: approve req 返回后设 approvalResult state，展示 modal 含 API Key code 块 + 复制到剪贴板按钮，关闭后不可再看到
- [x] **S9-08** `web/src/admin/AdminKnowledge.tsx:74` — `price || ''` 吞掉 price=0（免费产品）。改为 `price ?? ''` → fixed: 产品价格 input 使用 value={newProduct.price ?? ''}
- [x] **S9-09** `web/src/admin/AdminPlatforms.tsx` — `PlatformConfig` Type 缺 `app_secret`/`token`/`encoding_aes_key` 字段。补全字段 → fixed: PlatformConfig 接口含 app_secret/token/encoding_aes_key，editForm state 含所有字段，编辑时显示对应 input
- [x] **S9-10** `web/public/widget.js` — iframe URL `baseUrl + '/widget?tenant_id=...'` 但 React 路由表无 `/widget` 路由。加路由或在 App.tsx 处理 → fixed: App.tsx 中已加 <Route path="/widget" element={<WidgetPage />} />，WidgetPage 用 query string 读 tenant_id 渲染 ChatContainer

---

## 🟡 Medium (7 条)

- [x] **S9-11** `web/src/cards/WorkshopCard.tsx:20` — 产品链接跳 `/product/:id` 但路由不存在。改为 `#` 或实现详情路由 → fixed: 已改为 window.open(product.image_url, '_blank')，点击在新标签页打开产品图片
- [x] **S9-12** `web/src/cards/InterruptCard.tsx:25` — timer `useEffect` 在父组件 re-render 时重置。用 `useRef` 存 timer → fixed: timer 引用存于 intervalRef (useRef)，onReply 引用存于 onReplyRef (useRef) 避免闭包陈旧值，expiredRef 存于 useRef 避免重复超时触发
- [x] **S9-13** `web/src/cards/InterruptCard.tsx` — `InterruptCardData` 缺 `session_id` / `interrupt_id` 字段 → fixed: InterruptCardData 接口含 session_id:string 和 interrupt_id:string，narrowCard validator 已校验二者都为 string
- [x] **S9-14** `web/src/cards/WorkshopCard.tsx` — `<img>` 无 `onError` 处理，图片加载失败显示破碎图标 → fixed: 已加 onError handler，设置 src 为内联 SVG placeholder（显示"无图"）
- [x] **S9-15** `web/src/admin/AdminDashboard.tsx` — 无自动刷新。加 30s 轮询或 SSE → fixed: 已加 30s setInterval 轮询，含挂载保护、静默错误、cleanup
- [x] **S9-16** `web/src/admin/AdminKnowledge.tsx` — 产品和冲突规则无分页。大量数据时 DOM 堆积 → fixed: 已加 Pager 组件，PAGE_SIZE=15，按 tab 重置页码
- [x] **S9-17** `web/src/admin/AdminSessions.tsx:42-72` — `tenant_id` filter 输入 `Number()` 可能产生 NaN → fixed: 已加 isNaN guard，NaN 时清除 undefined 而非 NaN

---

## 🟢 Low (13 条)

- [x] **S9-18** `web/public/sw.js:30-44` — 缓存策略是 network-first 而非 stale-while-revalidate → fixed: 已改为 swr，cached || fetchPromise
- [x] **S9-19** `web/public/sw.js` — `CACHE_NAME` 硬编码 `agentos-v0.3`，每次部署需手动改 → fixed: 改用 Date.now() 动态生成缓存名
- [x] **S9-20** `web/src/main.tsx` — SW 注册后不监听 `updatefound`/`statechange`，用户收不到新版本通知 → fixed: 已加 updatefound/statechange 监听，弹窗提示刷新
- [x] **S9-21** `web/public/manifest.json` — 缺 `"purpose": "any maskable"` 在 icon 条目上 → fixed: 已加 purpose 字段
- [x] **S9-22** `web/public/manifest.json` — `"orientation": "portrait-primary"` 限制横屏 → fixed: 已删除 orientation 字段
- [x] **S9-23** `web/public/widget.js` — 无 `sandbox` 属性在 iframe 上 → fixed: 已加 sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
- [x] **S9-24** `web/public/widget.js` — CSS `position: fixed` 可能与宿主页面 fixed 元素冲突 → fixed: 已用 Shadow DOM (mode:closed) + :host{all:initial} 隔离样式
- [x] **S9-25** `web/public/widget.js` — 域名 hardcode `hufu.cn` → fixed: 已改为从 script tag data-api-base 属性读，默认 hufu.cn
- [x] **S9-26** `web/src/pages/RegisterPage.tsx` — 密码规则与 PRD 不符 → fixed: 改为 8-32 位 + 大写 + 小写 + 数字校验，placeholder 和 minLength 同步更新
- [x] **S9-27** `web/src/pages/RegisterPage.tsx` — 手机号无格式校验 → fixed: 已加纯数字正则 + 11位长度双重校验
- [x] **S9-28** `web/src/admin/AdminKnowledge.tsx` — tabs 缺 WAI-ARIA → fixed: 已加 role="tablist"/role="tab"/aria-selected/aria-controls/role="tabpanel"/id
- [x] **S9-29** `web/src/admin/AdminTenants.tsx` — `handleApprove` 发空 body vs `handleReject` → fixed: 统一为 PUT 不带 JSON body，后端从 URL path 获取 action
- [x] **S9-30** `web/package.json` — `react-router-dom ^7.17.0` 可能与 v6 API 不兼容 → fixed: 已降级为 ^6.30.4，与代码中 Navigate/useNavigate/useSearchParams 等 v6 API 兼容
- [x] **S9-31** `web/vite.config.ts` — 无 `base` 路径配置 → fixed: 已加 base: process.env.VITE_BASE || '/'，支持子路径部署
- [x] **S9-32** `web/tsconfig.json` — `noUnusedLocals`/`noUnusedParameters` 启用但代码中有未用变量 → fixed: 修复 test 文件中未使用的 InterruptRequest 导入和 instanceCountBefore 变量，tsc --noEmit 通过
