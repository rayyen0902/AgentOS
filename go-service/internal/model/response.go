package model

import "encoding/json"

type APIResponse struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
	TraceID string          `json:"trace_id"`
}

func NewSuccessResponse(data interface{}, traceID string) APIResponse {
	var raw json.RawMessage
	if data != nil {
		raw, _ = json.Marshal(data)
	}
	return APIResponse{Code: 0, Message: "ok", Data: raw, TraceID: traceID}
}

func NewErrorResponse(code int, message string, traceID string) APIResponse {
	return APIResponse{Code: code, Message: message, Data: nil, TraceID: traceID}
}
