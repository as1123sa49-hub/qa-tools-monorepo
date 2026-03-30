/**
 * content.js — 在頁面 JS 執行前注入 page-script.js
 * 必須在 document_start 執行，才能在 WebSocket 建立前替換 window.WebSocket
 */
(function () {
  const script = document.createElement('script');
  script.src = chrome.runtime.getURL('page-script.js');
  script.onload = () => script.remove();
  (document.head || document.documentElement).appendChild(script);
})();
