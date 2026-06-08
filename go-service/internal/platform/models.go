package platform

import (
	"time"
)

// --- Normalized internal message (doc section 7.4) ---

// InboundMessage is the unified internal message format.
// All platform messages are normalized to this structure before forwarding to Python.
type InboundMessage struct {
	SessionID  string      `json:"session_id"`
	UserID     int64       `json:"user_id"`
	TenantID   int64       `json:"tenant_id"`
	Platform   string      `json:"platform"` // web | wecom | douyin | xhs
	Message    MessageBody `json:"message"`
	AgentState interface{} `json:"agent_state"`
}

// MessageBody holds the content of an incoming message.
type MessageBody struct {
	Type     string  `json:"type"`     // text | image | interrupt_reply
	Content  string  `json:"content"`
	ImageURL *string `json:"image_url"`
}

// --- Platform configuration ---

// TenantPlatform represents a row in the tenant_platforms table.
type TenantPlatform struct {
	ID                 int64     `json:"id"`
	TenantID           int64     `json:"tenant_id"`
	Platform           string    `json:"platform"` // wecom | douyin | xhs
	AppID              string    `json:"app_id"`
	AppSecretHash      string    `json:"app_secret_hash"`      // SHA-256 for signature verification
	AppSecretEncrypted string    `json:"app_secret_encrypted"` // AES-256-GCM encrypted
	Token              string    `json:"token"`                // 企微 token
	EncodingAESKey     string    `json:"encoding_aes_key"`     // 企微 AES key
	WeComAgentID       int       `json:"wecom_agent_id"`       // S7-07: 企微 AgentID, default 1000002
	WebhookURL         string    `json:"webhook_url"`
	Status             string    `json:"status"`
	CreatedAt          time.Time `json:"created_at"`
}

// --- WeCom types (doc section 7A) ---

// WeComVerifyParams holds GET verification query params.
type WeComVerifyParams struct {
	MsgSignature string `json:"msg_signature"`
	Timestamp    string `json:"timestamp"`
	Nonce        string `json:"nonce"`
	Echostr      string `json:"echostr"`
}

// WeComEncryptedMsg is the raw XML structure received from WeCom.
type WeComEncryptedMsg struct {
	ToUserName string `xml:"ToUserName"`
	AgentID    string `xml:"AgentID"`
	Encrypt    string `xml:"Encrypt"`
}

// WeComDecryptedMsg is the decrypted XML payload.
type WeComDecryptedMsg struct {
	ToUserName   string `xml:"ToUserName"`
	FromUserName string `xml:"FromUserName"`
	CreateTime   int64  `xml:"CreateTime"`
	MsgType      string `xml:"MsgType"`
	Content      string `xml:"Content"`
	MsgID        int64  `xml:"MsgId"`
	AgentID      int    `xml:"AgentID"`
	PicURL       string `xml:"PicUrl"`
}

// WeComPassiveReply is the passive XML response (sync).
type WeComPassiveReply struct {
	XMLName      string `xml:"xml"`
	ToUserName   string `xml:"ToUserName"`
	FromUserName string `xml:"FromUserName"`
	CreateTime   int64  `xml:"CreateTime"`
	MsgType      string `xml:"MsgType"`
	Content      string `xml:"Content"`
}

// WeComActivePush is the JSON body for POST /cgi-bin/message/send.
type WeComActivePush struct {
	ToUser  string           `json:"touser"`
	MsgType string           `json:"msgtype"`
	AgentID int              `json:"agentid"`
	Text    *WeComTextContent `json:"text,omitempty"`
	News    *WeComNewsContent `json:"news,omitempty"`
}

// WeComTextContent is text message content for active push.
type WeComTextContent struct {
	Content string `json:"content"`
}

// WeComNewsContent is a card/news message for active push.
type WeComNewsContent struct {
	Articles []WeComArticle `json:"articles"`
}

// WeComArticle is a single article/item in a news card.
type WeComArticle struct {
	Title       string `json:"title"`
	Description string `json:"description"`
	URL         string `json:"url"`
	PicURL      string `json:"picurl,omitempty"`
}

// WeComTokenResponse is the response from /cgi-bin/gettoken.
type WeComTokenResponse struct {
	ErrCode     int    `json:"errcode"`
	ErrMsg      string `json:"errmsg"`
	AccessToken string `json:"access_token"`
	ExpiresIn   int    `json:"expires_in"`
}

// --- Douyin types (doc section 7B) ---

// DouyinVerifyParams holds GET verification query params.
type DouyinVerifyParams struct {
	Signature string `json:"signature"`
	Timestamp string `json:"timestamp"`
	Nonce     string `json:"nonce"`
	Echostr   string `json:"echostr"`
}

// DouyinWebhookBody is the raw POST body from Douyin.
type DouyinWebhookBody struct {
	ToUserID   string     `json:"touserid"`
	FromUserID string     `json:"fromuserid"`
	MsgType    string     `json:"msg_type"`
	Content    DouyinText `json:"content"`
	Timestamp  int64      `json:"timestamp"`
}

// DouyinText holds text message content.
type DouyinText struct {
	Text string `json:"text"`
}

// DouyinSendMsgReq is the request body for POST /im/send_msg/.
type DouyinSendMsgReq struct {
	FromUserID  string `json:"from_user_id"`
	ToUserID    string `json:"to_user_id"`
	MsgType     string `json:"msg_type"`
	Content     string `json:"content"`
	TenantID    string `json:"tenant_id"`
}

// --- Xiaohongshu types (doc section 7C) ---

// XHSVerifyParams holds GET verification query params.
type XHSVerifyParams struct {
	Signature string `json:"signature"`
	Timestamp string `json:"timestamp"`
	Nonce     string `json:"nonce"`
	Echostr   string `json:"echostr"`
}

// XHSWebhookBody is the raw POST body from Xiaohongshu.
type XHSWebhookBody struct {
	MsgType    string `json:"msg_type"`
	FromUserID string `json:"from_user_id"`
	ToUserID   string `json:"to_user_id"`
	Content    string `json:"content"`
	MsgID      string `json:"msg_id"`
}

// XHSSendMsgReq is the request body for private message API.
type XHSSendMsgReq struct {
	ToUserID string `json:"to_user_id"`
	MsgType  string `json:"msg_type"`
	Content  string `json:"content"`
}

// --- InterruptCard for active push (doc section 7.1) ---

// InterruptCard is the unified format for pushing interrupts to users.
type InterruptCard struct {
	InterruptID string   `json:"interrupt_id"`
	Question    string   `json:"question"`
	Options     []string `json:"options"`
	TimeoutS    int      `json:"timeout_s"`
}
