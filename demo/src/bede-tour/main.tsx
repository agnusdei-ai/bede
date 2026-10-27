import { createRoot } from "react-dom/client";
import { Tour } from "./Tour";

const root = document.getElementById("root");
if (!root) throw new Error("Bede tour root is missing.");
createRoot(root).render(<Tour />);
