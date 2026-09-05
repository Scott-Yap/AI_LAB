import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./KnowledgeGraph", () => ({ KnowledgeGraph: () => <div>Graph</div> }));
vi.mock("./api", () => {
  let reads = 0;
  return {
    streamMessage: vi.fn(),
    api: vi.fn(async (path: string) => {
      if (path === "/settings") return { instructions: "Teach", think: false };
      if (path === "/conversations")
        return [{ id: "one", title: "Question", updated_at: "2026-09-05" }];
      if (path === "/graph") return { nodes: [], edges: [] };
      if (path === "/health") return { reachable: true, model_available: true };
      if (path === "/textbook/status")
        return { state: "ready", searchable: true };
      if (path.endsWith("/messages")) {
        reads++;
        return [
          {
            id: "u",
            role: "user",
            content: "Question",
            status: "complete",
            sources: [],
            think: false,
          },
          {
            id: "a",
            role: "assistant",
            content: "",
            status: reads === 1 ? "streaming" : "interrupted",
            sources: [],
            think: false,
          },
        ];
      }
      throw new Error(path);
    }),
  };
});

it("refreshes a response finalized after cancellation and exposes retry without a reload", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("Question")).toBeInTheDocument());
  await waitFor(
    () =>
      expect(
        screen.getByRole("button", { name: "Retry response" }),
      ).toBeEnabled(),
    { timeout: 3000 },
  );
});
