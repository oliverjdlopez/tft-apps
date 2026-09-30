/** Display only the launcher's plain-text status on the isolated startup page. */
document.getElementById("status").textContent = new URLSearchParams(location.search).get("message") || "Starting ChatTFT…";
