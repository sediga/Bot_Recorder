(function () {
  if (document.getElementById("botflows-loop-banner")) return;

  const banner = document.createElement("div");
  banner.id = "botflows-loop-banner";
  banner.innerText = window.__botflows_loopName__ 
    ? `🎯 Recording inside loop: "${window.__botflows_loopName__}"`
    : `🎯 Recording inside loop...`;

  Object.assign(banner.style, {
    position: "fixed",
    top: "12px",
    right: "12px",
    background: "#fefcbf",
    color: "#202020",
    padding: "10px 14px",
    fontSize: "14px",
    fontWeight: "bold",
    fontFamily: "sans-serif",
    borderRadius: "8px",
    border: "1px solid #d69e2e",
    zIndex: 999999,
    boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
  });

  document.body.appendChild(banner);
})();
