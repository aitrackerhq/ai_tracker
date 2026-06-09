// main.jsx — MODIFIED
// Change: wrap app with <AuthProvider>
// Everything else is identical to the original.

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./contexts/AuthContext.jsx"; // ← ADD
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        {" "}
        {/* ← ADD */}
        <App />
      </AuthProvider>{" "}
      {/* ← ADD */}
    </BrowserRouter>
  </React.StrictMode>,
);
