import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ChatInput } from './ChatInput';
import { useChatStore } from '../store/chatStore';

// ============================================================
// validate is NOT exported — tested via component behaviour
// ============================================================
// The `validate` function is defined inside ChatInput and scoped
// to handleSubmit. Its logic is:
//   - length > 2000  → { valid: false, content: sliced, truncated: true }
//   - otherwise       → { valid: true,  content,         truncated: false }
// The input has maxLength=2000 so the truncation path is a
// defence-in-depth layer in case the HTML attribute is bypassed.
// We verify it through the component's submit behaviour.

// ============================================================
// Helpers
// ============================================================

const INITIAL_STORE_STATE = {
  messages: [] as any[],
  statusStream: [] as any[],
  interrupt: null,
  currentCard: null,
  errorEvent: null,
  isProcessing: false,
  sseConnected: false,
};

function resetStore() {
  useChatStore.setState({ ...INITIAL_STORE_STATE });
}

function enterText(text: string) {
  const input = screen.getByPlaceholderText('输入消息...');
  fireEvent.change(input, { target: { value: text } });
}

// ============================================================
// ChatInput component tests
// ============================================================

describe('ChatInput', () => {
  beforeEach(() => {
    resetStore();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // --- rendering ---

  it('renders a text input with placeholder', () => {
    render(<ChatInput />);
    expect(screen.getByPlaceholderText('输入消息...')).toBeTruthy();
  });

  it('renders a send button', () => {
    render(<ChatInput />);
    expect(screen.getByRole('button', { name: '发送' })).toBeTruthy();
  });

  it('renders an attach (image upload) button', () => {
    render(<ChatInput />);
    expect(screen.getByTitle('上传图片')).toBeTruthy();
  });

  it('has maxLength of 2000 on the text input', () => {
    render(<ChatInput />);
    const input = screen.getByPlaceholderText('输入消息...') as HTMLInputElement;
    expect(input.maxLength).toBe(2000);
  });

  // --- send button disabled states ---

  it('send button is disabled when input is empty', () => {
    render(<ChatInput />);
    const btn = screen.getByRole('button', { name: '发送' }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('send button is enabled when input has text', () => {
    render(<ChatInput />);
    enterText('hello');
    const btn = screen.getByRole('button', { name: '发送' }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('send button is disabled when isProcessing is true', () => {
    useChatStore.setState({ isProcessing: true });
    render(<ChatInput />);
    enterText('hello');
    const btn = screen.getByRole('button', { name: '发送' }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('text input is disabled when isProcessing is true', () => {
    useChatStore.setState({ isProcessing: true });
    render(<ChatInput />);
    const input = screen.getByPlaceholderText('输入消息...') as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });

  // --- submission ---

  it('clears input after successful submit', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello world');

    const input = screen.getByPlaceholderText('输入消息...') as HTMLInputElement;
    expect(input.value).toBe('hello world');

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(input.value).toBe('');
    });
  });

  it('sets isProcessing true on submit', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(useChatStore.getState().isProcessing).toBe(true);
    });
  });

  it('appends a user message to the store on submit', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      const msgs = useChatStore.getState().messages;
      expect(msgs.length).toBe(1);
      expect(msgs[0].role).toBe('user');
      expect(msgs[0].content).toBe('hello');
    });
  });

  it('does not submit empty/whitespace input', () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('   ');

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    expect(mockFetch).not.toHaveBeenCalled();
    expect(useChatStore.getState().messages.length).toBe(0);
  });

  it('does not submit when isProcessing is already true', () => {
    useChatStore.setState({ isProcessing: true });
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    // The input should be disabled; try submitting anyway
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    expect(mockFetch).not.toHaveBeenCalled();
  });

  // --- error display ---

  it('shows error message when fetch returns non-ok', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ message: '服务端错误' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText('服务端错误')).toBeTruthy();
    });
  });

  it('shows fallback error when response has no message', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText('发送失败，请重试')).toBeTruthy();
    });
  });

  it('shows network error when fetch throws', async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error('Network'));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText('网络错误，请检查连接')).toBeTruthy();
    });
  });

  it('dismisses error when x button is clicked', async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error('Network'));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('hello');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText('网络错误，请检查连接')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('x'));

    await waitFor(() => {
      expect(screen.queryByText('网络错误，请检查连接')).toBeNull();
    });
  });

  // --- truncation via validate (defence-in-depth: maxLength exists on DOM) ---

  it('shows truncation error when input exceeds 2000 chars (jsdom bypasses maxLength)', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    // jsdom does NOT enforce maxLength on fireEvent.change, so the
    // validate → truncation path is reachable
    const longText = 'a'.repeat(2001);
    enterText(longText);

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText(/消息过长，已截断至\d+字/)).toBeTruthy();
      // validate slices to 2000 characters
      const input = screen.getByPlaceholderText('输入消息...') as HTMLInputElement;
      expect(input.value).toBe('a'.repeat(2000));
    });
  });

  it('accepts exactly 2000 chars without truncation', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    const exact = 'b'.repeat(2000);
    enterText(exact);

    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      const input = screen.getByPlaceholderText('输入消息...') as HTMLInputElement;
      expect(input.value).toBe('');
      expect(screen.queryByText(/消息过长/)).toBeNull();
    });
  });

  // --- auth header ---

  it('includes Authorization header when jwt exists in localStorage', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);
    localStorage.setItem('jwt', 'test-token');

    render(<ChatInput />);
    enterText('auth test');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
      const callArgs = mockFetch.mock.calls[0];
      expect(callArgs[1].headers.Authorization).toBe('Bearer test-token');
    });
  });

  it('omits Authorization header when jwt is absent', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatInput />);
    enterText('no auth test');
    fireEvent.submit(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
      const callArgs = mockFetch.mock.calls[0];
      expect(callArgs[1].headers.Authorization).toBeUndefined();
    });
  });

  // --- image upload error (file size) ---

  it('shows error when selected image exceeds 10 MB', async () => {
    render(<ChatInput />);

    const fileInput = screen.getByTitle('上传图片').parentElement!.querySelector('input[type="file"]')!;
    const largeFile = new File(['x'.repeat(11 * 1024 * 1024)], 'large.jpg', { type: 'image/jpeg' });

    fireEvent.change(fileInput, { target: { files: [largeFile] } });

    await waitFor(() => {
      expect(screen.getByText('图片过大，请重新上传（上限10MB）')).toBeTruthy();
    });
  });
});
