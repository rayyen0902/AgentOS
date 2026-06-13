package sse

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestNewBroker(t *testing.T) {
	b := NewBroker()
	assert.NotNil(t, b)
}

func TestBuildEvent(t *testing.T) {
	evt := BuildEvent("test_event", `{"key":"value"}`)
	assert.Equal(t, "test_event", evt.Event)
	assert.JSONEq(t, `{"key":"value"}`, string(evt.Data.(json.RawMessage)))
}

func TestSubscribe(t *testing.T) {
	b := NewBroker()
	ch, unsub := b.Subscribe("s1")

	assert.NotNil(t, ch)
	assert.NotNil(t, unsub)

	// Calling unsubscribe should remove the channel and close it (after draining)
	unsub()

	// Verify channel is closed after unsub
	_, ok := <-ch
	assert.False(t, ok, "channel should be closed after unsubscribe")
}

func TestSubscribeMultiple(t *testing.T) {
	b := NewBroker()
	ch1, _ := b.Subscribe("s1")
	ch2, _ := b.Subscribe("s2")

	assert.NotNil(t, ch1)
	assert.NotNil(t, ch2)
	assert.NotEqual(t, ch1, ch2, "different sessions should have different channels")
}

func TestPublish(t *testing.T) {
	b := NewBroker()
	ch, unsub := b.Subscribe("s1")
	defer unsub()

	expected := BuildEvent("status", `{"msg":"ok"}`)
	b.Publish("s1", expected)

	received := <-ch
	assert.Equal(t, expected.Event, received.Event)
}

func TestPublishNoSubscribers(t *testing.T) {
	b := NewBroker()
	// Publish to a session with no subscribers — should not panic
	assert.NotPanics(t, func() {
		b.Publish("nonexistent", BuildEvent("test", `{}`))
	})
}

func TestPublishToWrongSession(t *testing.T) {
	b := NewBroker()
	ch, unsub := b.Subscribe("sA")
	defer unsub()

	// Publish to a different session
	b.Publish("sB", BuildEvent("test", `{}`))

	// sA's channel should NOT receive the event
	select {
	case evt := <-ch:
		t.Fatalf("unexpected event received on sA channel: %v", evt)
	default:
		// expected — no event
	}
}

func TestUnsubscribeIdempotent(t *testing.T) {
	b := NewBroker()
	_, unsub := b.Subscribe("s1")

	// First unsubscribe — should work
	assert.NotPanics(t, func() {
		unsub()
	})

	// Second unsubscribe — should be safe (no panic)
	assert.NotPanics(t, func() {
		unsub()
	})
}

func TestUnsubscribeDrainsChannel(t *testing.T) {
	b := NewBroker()
	ch, unsub := b.Subscribe("s1")

	// Publish an event without reading it
	b.Publish("s1", BuildEvent("evt", `{}`))

	// Unsubscribe drains and closes the channel
	unsub()

	// Reading from a closed channel returns zero value and ok=false
	_, ok := <-ch
	assert.False(t, ok, "channel should be closed after unsubscribe")
}

func TestRacePublishUnsubscribe(t *testing.T) {
	b := NewBroker()
	var wg sync.WaitGroup

	// Spawn 100 goroutines: half publish to random sessions, half subscribe+unsubscribe
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			sid := "publish_session"
			// Subscribe once to ensure the session exists in the broker
			_, unsub := b.Subscribe(sid)
			defer unsub()
			for j := 0; j < 10; j++ {
				b.Publish(sid, BuildEvent("test", `{}`))
			}
		}(i)

		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			sid := "subscribe_session"
			ch, unsub := b.Subscribe(sid)
			// Start a goroutine to drain
			go func() {
				for range ch {
				}
			}()
			b.Publish(sid, BuildEvent("test", `{}`))
			unsub()
		}(i)
	}

	wg.Wait()
}

func TestHandler(t *testing.T) {
	b := NewBroker()
	sessionID := "test-handler-session"

	// Create an HTTP request with session_id query param.
	req := httptest.NewRequest(http.MethodGet, "/sse?session_id="+sessionID, nil)

	// Use a context with cancel to simulate client disconnect.
	ctx, cancel := context.WithCancel(context.Background())
	req = req.WithContext(ctx)

	rr := httptest.NewRecorder()

	// Run Handler in a goroutine since it blocks.
	done := make(chan struct{})
	go func() {
		defer close(done)
		b.Handler(rr, req)
	}()

	// Wait a short time for the connected event to be written.
	time.Sleep(50 * time.Millisecond)

	// Publish an event so the handler sends it over SSE.
	b.Publish(sessionID, BuildEvent("test_event", `{"key":"value"}`))

	// Give the handler time to receive and write the published event.
	time.Sleep(50 * time.Millisecond)

	// Cancel the context to trigger r.Context().Done() and clean up.
	cancel()

	// Wait for handler to exit before reading the response body (avoids data race).
	<-done

	// Now it's safe to read the response.
	resp := rr.Result()
	body := make([]byte, 2048)
	n, _ := resp.Body.Read(body)
	resp.Body.Close()

	bodyStr := string(body[:n])
	assert.Contains(t, bodyStr, "event: connected", "initial connected event should be sent")
	assert.Contains(t, bodyStr, `"session_id":"`+sessionID+`"`, "connected event should contain session_id")
	assert.Contains(t, bodyStr, "event: test_event", "published test_event should be received")

	// Verify SSE headers are set.
	assert.Equal(t, "text/event-stream", resp.Header.Get("Content-Type"))
	assert.Equal(t, "no-cache", resp.Header.Get("Cache-Control"))
	assert.Equal(t, "keep-alive", resp.Header.Get("Connection"))
}
