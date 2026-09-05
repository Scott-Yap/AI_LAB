import { useEffect, useRef, useState } from "react";
import { BookOpen, RefreshCw, Save, X } from "lucide-react";
import { api } from "./api";
import type { Health, IndexStatus, Settings } from "./types";

export function SettingsDialog({
  settings,
  index,
  health,
  onClose,
  onSave,
  onIndex,
}: {
  settings: Settings;
  index: IndexStatus | null;
  health: Health | null;
  onClose: () => void;
  onSave: (value: Settings) => void;
  onIndex: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [instructions, setInstructions] = useState(settings.instructions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function save() {
    setSaving(true);
    setError("");
    try {
      onSave(
        await api<Settings>("/settings", {
          method: "PUT",
          body: JSON.stringify({ ...settings, instructions }),
        }),
      );
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <dialog
      className="settings-dialog"
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="settings-title"
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">MAKE IT YOURS</span>
          <h2 id="settings-title">Tutor settings</h2>
        </div>
        <button aria-label="Close settings" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      <div className="dialog-body">
        <label className="instructions-label" htmlFor="instructions">
          Tutor Instructions
        </label>
        <p className="muted">
          Shape how your tutor teaches. Saved locally and applied to subsequent
          messages.
        </p>
        <textarea
          id="instructions"
          value={instructions}
          maxLength={12000}
          onChange={(e) => setInstructions(e.target.value)}
          spellCheck={false}
        />
        <div className="field-note">
          <span>System and source-grounding rules are managed separately.</span>
          <span>{instructions.length.toLocaleString()} / 12,000</span>
        </div>
        <section className="index-card">
          <div className="index-title">
            <BookOpen size={19} />
            <strong>Your textbook</strong>
            <span className={`state-pill ${index?.state}`}>
              {index?.state.replaceAll("_", " ") ?? "Checking…"}
            </span>
          </div>
          <p>
            <strong>AI Engineering</strong>
            <br />
            Chip Huyen · Building Applications with Foundation Models
          </p>
          {index?.state === "indexing" && (
            <>
              <progress max={100} value={index.progress ?? 0} />
              <p className="muted">
                Embedding textbook passages… {index.progress ?? 0}%
              </p>
            </>
          )}
          {index?.searchable && (
            <p className="muted">
              {index.active_index?.chunk_count.toLocaleString()} searchable
              passages · Stored on this computer
            </p>
          )}
          {!index?.source_found && (
            <p className="inline-error">
              EPUB not found or ambiguous. Set TEXTBOOK_PATH in .env, then
              restart the backend.
            </p>
          )}
          {index?.error && (
            <p className="inline-error" role="alert">
              {index.error}
            </p>
          )}
          {index?.state === "failed" && index.searchable && (
            <p className="muted">
              The previous index is still available for search.
            </p>
          )}
          <button
            className="secondary"
            disabled={index?.state === "indexing" || !index?.source_found}
            onClick={() => void onIndex().catch((e) => setError(e.message))}
          >
            <RefreshCw size={15} />
            {index?.searchable ? "Rebuild index" : "Index textbook"}
          </button>
        </section>
        <div className="runtime-info">
          <span className="eyebrow">LOCAL RUNTIME</span>
          <p>
            {health?.model ?? "qwen3.5:9b"}{" "}
            <span>
              · {health?.model_available ? "Available" : "Unavailable"}
            </span>
          </p>
          <p>
            {health?.embedding_model ?? "nomic-embed-text:v1.5"}{" "}
            <span>
              ·{" "}
              {health?.embedding_available
                ? "Available"
                : "Run ollama pull nomic-embed-text:v1.5"}
            </span>
          </p>
        </div>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="dialog-footer">
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary"
          disabled={saving || !instructions.trim()}
          onClick={() => void save()}
        >
          <Save size={15} />
          {saving ? "Saving…" : "Save instructions"}
        </button>
      </div>
    </dialog>
  );
}
