import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SettingsDialog } from "./SettingsDialog";

afterEach(() => vi.unstubAllGlobals());
it("saves edited instructions and preserves the actual thinking preference", async () => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  const onSave = vi.fn(),
    onClose = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response('{"instructions":"Ask me to predict","think":true}'),
      ),
  );
  render(
    <SettingsDialog
      settings={{ instructions: "Original", think: true }}
      index={null}
      health={null}
      onSave={onSave}
      onClose={onClose}
      onIndex={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Tutor Instructions"), {
    target: { value: "Ask me to predict" },
  });
  fireEvent.click(screen.getByText("Save instructions"));
  await waitFor(() =>
    expect(onSave).toHaveBeenCalledWith({
      instructions: "Ask me to predict",
      think: true,
    }),
  );
  expect(onClose).toHaveBeenCalled();
  expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual(
    { instructions: "Ask me to predict", think: true },
  );
});
