import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import TradingIQChallenge from "./pages/TradingIQChallenge.jsx";
import "./index.css";
createRoot(document.getElementById("root")).render(<BrowserRouter><TradingIQChallenge /></BrowserRouter>);

// Forward existing Academy links to the main site without changing approved lesson components.
document.addEventListener("click", event => {
 const link=event.target.closest?.("a[href]");
 if(!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
 const target=new URL(link.href);
 if(target.origin === window.location.origin && target.pathname.startsWith("/academy/")) {
  event.preventDefault(); window.location.assign("https://nijaaitrading.com" + target.pathname + target.search + target.hash);
 }
}, true);
