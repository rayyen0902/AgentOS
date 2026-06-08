package sse

import (
	"encoding/json"
	"sync"
	"testing"

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
