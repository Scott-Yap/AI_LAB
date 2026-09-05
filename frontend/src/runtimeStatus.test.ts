import { expect, it } from "vitest";
import { runtimeStatus } from "./runtimeStatus";

it("distinguishes installed, loaded, missing, and unreachable models", () => {
  const health = {
    reachable: true,
    model: "qwen",
    embedding_model: "embed",
    model_available: true,
    embedding_available: true,
    model_loaded: false,
    embedding_loaded: false,
  };
  expect(runtimeStatus(health)).toBe("Models unloaded · load on demand");
  expect(runtimeStatus({ ...health, model_loaded: true })).toBe(
    "Qwen loaded · retriever unloaded",
  );
  expect(runtimeStatus({ ...health, embedding_loaded: true })).toBe(
    "Qwen unloaded · retriever loaded",
  );
  expect(
    runtimeStatus({ ...health, model_loaded: true, embedding_loaded: true }),
  ).toBe("Both models loaded");
  expect(runtimeStatus({ ...health, embedding_available: false })).toBe(
    "Required models missing",
  );
  expect(runtimeStatus({ ...health, reachable: false })).toBe(
    "Ollama unreachable",
  );
  expect(runtimeStatus({ ...health, model_loaded: null })).toBe(
    "Model memory status unknown",
  );
});
