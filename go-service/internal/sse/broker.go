package sse

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

type Broker struct {
	mu       sync.RWMutex
	channels map[string]map[chan SSEEvent]struct{}
}

type SSEEvent struct {
	Event string
	Data  interface{}
}

func NewBroker() *Broker {
	return &Broker{
		channels: make(map[string]map[chan SSEEvent]struct{}),
	}
}

func (b *Broker) Subscribe(sessionID string) (chan SSEEvent, func()) {
	b.mu.Lock()
	defer b.mu.Unlock()
	ch := make(chan SSEEvent, 64)
	if b.channels[sessionID] == nil {
		b.channels[sessionID] = make(map[chan SSEEvent]struct{})
	}
	b.channels[sessionID][ch] = struct{}{}
	unsubscribe := func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		delete(b.channels[sessionID], ch)
		close(ch)
	}
	return ch, unsubscribe
}

func (b *Broker) Publish(sessionID string, evt SSEEvent) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	subs := b.channels[sessionID]
	for ch := range subs {
		select {
		case ch <- evt:
		default:
		}
	}
}

// Handler serves SSE connection for a session.
func (b *Broker) Handler(w http.ResponseWriter, r *http.Request) {
	sessionID := r.URL.Query().Get("session_id")
	if sessionID == "" {
		http.Error(w, `{"code":4001,"message":"session_id required"}`, http.StatusBadRequest)
		return
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	ch, unsub := b.Subscribe(sessionID)
	defer unsub()

	// Write initial session_id in the first heartbeat-like event
	fmt.Fprintf(w, "event: connected\ndata: {\"session_id\":\"%s\"}\n\n", sessionID)
	flusher.Flush()

	heartbeat := time.NewTicker(30 * time.Second)
	defer heartbeat.Stop()

	for {
		select {
		case evt, ok := <-ch:
			if !ok {
				return
			}
			dataBytes, _ := json.Marshal(evt.Data)
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", evt.Event, string(dataBytes))
			flusher.Flush()
		case <-heartbeat.C:
			fmt.Fprintf(w, "event: heartbeat\ndata: {}\n\n")
			flusher.Flush()
		case <-r.Context().Done():
			return
		}
	}
}

// Helper to build SSE event from string data (used by handlers).
func BuildEvent(event string, data string) SSEEvent {
	return SSEEvent{Event: event, Data: json.RawMessage(data)}
}
