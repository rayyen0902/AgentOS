# Step 4：前端骨架

> **上下文范围**：PRD 第 16 节（前端重构）
> **前置依赖**：Step 3（Go SSE 端点可用）
> **完成标准**：React 应用启动，SSE 连接成功，基础消息渲染正常，Zustand Store 就位

---

## 4.1 技术选型

- React 18.3+ + TypeScript 5.x + Vite 5.x
- SSE：`EventSource`（内置重连）
- 状态管理：Zustand
- 嵌入模式：iframe + postMessage

---

## 4.2 架构分层

```
React SPA (Vite + TypeScript)
  · SSE订阅 · 消息渲染 · 状态卡片 · PWA
          │ HTTP + SSE
Go 路由层
```

React 层职责：
- **做**：Web Demo — 渲染 + SSE 订阅
- **不做**：不调 LLM、不写业务逻辑

---

## 4.3 SSE 事件类型（前端视角）

| event 名 | 触发时机 | data 格式 |
|----------|---------|-----------|
| `status` | Tool/Agent 状态变化 | `{"seq":1,"source":"tool:fe_retrieve","status":"running","label":"..."}` |
| `reply` | 文本回复就绪 | `{"text":"...", "from":"front_agent"}` |
| `interrupt` | 子 Agent 需要确认 | InterruptRequest JSON |
| `card` | 卡片数据就绪 | CardPayload JSON |
| `done` | 本轮全部完成 | `{"session_id":"...","total_ms":3500}` |
| `error` | Agent 报错 | `{"code":"AGENT_TIMEOUT","message":"..."}` |
| `heartbeat` | 每 30s 保活 | `{}` |

所有事件都带 `session_id` 字段，前端按 session_id 路由。

---

## 4.4 SSE 断线重连策略

```typescript
const useSSE = (sessionId: string) => {
  useEffect(() => {
    let retryCount = 0;
    const maxRetry = 10;
    const connect = () => {
      const es = new EventSource(`/api/v1/chat/stream?session_id=${sessionId}`);
      es.addEventListener('heartbeat', () => { retryCount = 0; });
      es.onerror = () => {
        es.close();
        if (retryCount < maxRetry) {
          const delay = Math.min(1000 * 2 ** retryCount, 30000); // 指数退避，最长30s
          setTimeout(connect, delay);
          retryCount++;
        }
      };
    };
    connect();
  }, [sessionId]);
};
```

---

## 4.5 Zustand Store 设计

```typescript
interface ChatStore {
  messages: Message[];
  statusStream: StatusEvent[];
  interrupt: InterruptRequest | null;
  currentCard: CardPayload | null;
  isProcessing: boolean;
  sseConnected: boolean;

  // actions
  appendMessage: (msg: Message) => void;
  appendStatus: (event: StatusEvent) => void;
  setInterrupt: (req: InterruptRequest | null) => void;
  setCard: (card: CardPayload | null) => void;
  finishProcessing: () => void;
  replyInterrupt: (option: string) => Promise<void>;
}
```

### 各字段/方法说明

| 字段/方法 | 说明 |
|-----------|------|
| `messages` | 消息列表，含用户消息和 AI 回复 |
| `statusStream` | Tool/Agent 实时状态流（按 seq 排序） |
| `interrupt` | 当前中断请求，非 null 时展示确认按钮 |
| `currentCard` | 当前卡片数据，非 null 时渲染对应卡片组件 |
| `isProcessing` | true = 正在等待 Agent 响应 |
| `sseConnected` | true = SSE 连接正常 |
| `appendMessage` | 收到 `reply` 事件时追加消息 |
| `appendStatus` | 收到 `status` 事件时追加/更新状态 |
| `setInterrupt` | 收到 `interrupt` 事件时设置中断 |
| `setCard` | 收到 `card` 事件时设置卡片 |
| `finishProcessing` | 收到 `done` 事件时重置 isProcessing |
| `replyInterrupt` | 用户选择中断选项后，POST 回复到服务端 |

---

## 4.6 组件树

```
App
├── ChatContainer
│   ├── MessageList
│   │   ├── UserMessage
│   │   └── AIMessage（文本 + 卡片）
│   ├── StatusBar（Tool/Agent 实时状态）
│   ├── InterruptPanel（确认按钮组）
│   └── ChatInput（消息输入框 + 发送按钮）
└── SSEProvider（SSE 连接管理）
```

---

## 4.7 数据边界

| 字段 | 最大值 | 超出处理 |
|------|--------|----------|
| 消息内容 | 2000 字 | 截断并提示"消息过长，已截断至2000字" |
| 图片大小 | 10MB | 拒绝并提示重新上传 |
| SSE 单事件 | 64KB | 大卡片分块推送（SSE multi-event） |

---

## 4.8 验收标准

- [ ] Vite + React + TypeScript 项目初始化
- [ ] Zustand Store 创建并接入所有组件
- [ ] SSE 连接成功，`heartbeat` 事件正常接收
- [ ] `reply` 事件 → 消息列表渲染
- [ ] `status` 事件 → StatusBar 实时更新
- [ ] `interrupt` 事件 → InterruptPanel 展示确认按钮
- [ ] `card` 事件 → 占位卡片区域渲染（具体卡片在 Step 9）
- [ ] `error` 事件 → 错误提示展示
- [ ] `done` 事件 → isProcessing 重置
- [ ] SSE 断线 → 自动重连（指数退避）
- [ ] 消息发送功能正常（POST /api/v1/chat/message）
