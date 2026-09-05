import { afterEach, describe, expect, it, vi } from "vitest";
import { streamMessage } from "./api";
import type { StreamEvent } from "./types";

afterEach(() => vi.unstubAllGlobals());
function mockStream(parts: string[]) {
  const encoder = new TextEncoder();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            parts.forEach((p) => controller.enqueue(encoder.encode(p)));
            controller.close();
          },
        }),
      ),
    ),
  );
}
describe("stream recovery boundaries", () => {
  it("handles split JSON lines and a final line without a newline", async () => {
    mockStream([
      '{"type":"token","text":"Hel',
      'lo"}\n{"type":"done","status":"complete"}',
    ]);
    const events: StreamEvent[] = [];
    await streamMessage(
      "id",
      "question",
      true,
      false,
      new AbortController().signal,
      (e) => events.push(e),
    );
    expect(events).toEqual([
      { type: "token", text: "Hello" },
      { type: "done", status: "complete" },
    ]);
    const request = vi.mocked(fetch).mock.calls[0][1];
    expect(JSON.parse(request?.body as string).think).toBe(true);
  });
  it("detects a stream that closes without completion", async () => {
    mockStream(['{"type":"token","text":"Partial"}\n']);
    await expect(
      streamMessage(
        "id",
        "q",
        false,
        false,
        new AbortController().signal,
        () => {},
      ),
    ).rejects.toThrow("interrupted");
  });
  it("propagates backend errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"Already running"}', { status: 409 }),
        ),
    );
    await expect(
      streamMessage(
        "id",
        "q",
        false,
        false,
        new AbortController().signal,
        () => {},
      ),
    ).rejects.toThrow("Already running");
  });
});
