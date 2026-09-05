export type Source = {
  chunk_id: string;
  title: string;
  chapter: string;
  section: string;
  source_id: string;
  score: number;
};
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  status: string;
  error?: string;
  think: boolean;
};
export type Conversation = { id: string; title: string; updated_at: string };
export type Settings = { instructions: string; think: boolean };
export type Health = {
  reachable: boolean;
  model: string;
  model_available: boolean;
  embedding_model: string;
  embedding_available: boolean;
  model_loaded?: boolean | null;
  embedding_loaded?: boolean | null;
  error?: string;
};
export type IndexStatus = {
  state: "not_indexed" | "indexing" | "ready" | "failed";
  chunk_count: number;
  progress?: number;
  error?: string;
  source_found: boolean;
  source_name?: string;
  searchable: boolean;
  active_index?: { indexed_at: string; chunk_count: number };
};
export type Concept = {
  id: string;
  name: string;
  description: string;
  chapter: string;
  section: string;
  status: string;
  position: { x: number; y: number };
};
export type Graph = {
  nodes: Concept[];
  edges: { id: string; source: string; target: string; relationship: string }[];
};
export type StreamEvent =
  | { type: "start"; message: Message }
  | { type: "token"; text: string }
  | { type: "reset" }
  | { type: "sources"; sources: Source[] }
  | { type: "status"; message: string }
  | { type: "warning"; message: string }
  | { type: "error"; message: string }
  | { type: "done"; status: string };
