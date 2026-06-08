package redisutil

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

const keyPrefix = "agentos:"

type Client struct {
	rdb    *redis.Client
	prefix string
}

func New(addr string) (*Client, error) {
	rdb := redis.NewClient(&redis.Options{
		Addr:         addr,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 3 * time.Second,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}

	return &Client{rdb: rdb, prefix: keyPrefix}, nil
}

func (c *Client) buildKey(key string) string {
	return c.prefix + key
}

func (c *Client) Get(ctx context.Context, key string) (string, error) {
	return c.rdb.Get(ctx, c.buildKey(key)).Result()
}

func (c *Client) Set(ctx context.Context, key string, value interface{}, ttl time.Duration) error {
	return c.rdb.Set(ctx, c.buildKey(key), value, ttl).Err()
}

func (c *Client) SetJSON(ctx context.Context, key string, value interface{}, ttl time.Duration) error {
	data, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	return c.rdb.Set(ctx, c.buildKey(key), data, ttl).Err()
}

func (c *Client) GetJSON(ctx context.Context, key string, dest interface{}) error {
	data, err := c.rdb.Get(ctx, c.buildKey(key)).Bytes()
	if err != nil {
		return err
	}
	return json.Unmarshal(data, dest)
}

func (c *Client) Delete(ctx context.Context, key string) error {
	return c.rdb.Del(ctx, c.buildKey(key)).Err()
}

func (c *Client) Exists(ctx context.Context, key string) (bool, error) {
	n, err := c.rdb.Exists(ctx, c.buildKey(key)).Result()
	return n > 0, err
}

func (c *Client) Expire(ctx context.Context, key string, ttl time.Duration) error {
	return c.rdb.Expire(ctx, c.buildKey(key), ttl).Err()
}

func (c *Client) XAdd(ctx context.Context, key string, values map[string]interface{}) error {
	return c.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: c.buildKey(key),
		Values: values,
	}).Err()
}

func (c *Client) Lock(ctx context.Context, lockKey string, ttl time.Duration) (bool, error) {
	return c.rdb.SetNX(ctx, c.buildKey(lockKey), "1", ttl).Result()
}

func (c *Client) Unlock(ctx context.Context, lockKey string) error {
	return c.rdb.Del(ctx, c.buildKey(lockKey)).Err()
}

// Incr atomically increments the counter at key and returns the new value.
func (c *Client) Incr(ctx context.Context, key string) (int64, error) {
	return c.rdb.Incr(ctx, c.buildKey(key)).Result()
}

func (c *Client) IsAvailable() bool {
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()
	return c.rdb.Ping(ctx).Err() == nil
}

func (c *Client) Close() error {
	return c.rdb.Close()
}
