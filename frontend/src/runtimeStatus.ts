import type { Health } from "./types";

export function runtimeStatus(health: Health | null) {
  if (!health) return "Checking local runtime…";
  if (!health.reachable) return "Ollama unreachable";
  if (!health.model_available || !health.embedding_available)
    return "Required models missing";
  if (health.model_loaded == null || health.embedding_loaded == null)
    return "Model memory status unknown";
  if (health.model_loaded && health.embedding_loaded)
    return "Both models loaded";
  if (health.model_loaded) return "Qwen loaded · retriever unloaded";
  if (health.embedding_loaded) return "Qwen unloaded · retriever loaded";
  return "Models unloaded · load on demand";
}
