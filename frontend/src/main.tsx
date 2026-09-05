import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./theme.css";
import { applyAppearance, readAppearance } from "./appearance";

// Apply the saved appearance before the first React render to avoid a light flash.
applyAppearance(readAppearance());
createRoot(document.getElementById("root")!).render(<App />);
