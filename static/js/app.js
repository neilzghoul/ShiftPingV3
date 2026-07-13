async function api(method, path, body) {
  const headers = {
    Accept: "application/json",
    "X-Admin-Token": window.ADMIN_TOKEN || "",
  };
  const opts = { method, headers, credentials: "same-origin" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text || "תגובה לא תקינה" };
  }
  if (!res.ok) {
    throw new Error((data && data.error) || "שגיאה " + res.status);
  }
  return data;
}

function toast(message, isError) {
  const el = document.getElementById("toast");
  if (!el) {
    alert(message);
    return;
  }
  el.hidden = false;
  el.textContent = message;
  el.classList.toggle("error", !!isError);
  clearTimeout(el._t);
  el._t = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

window.api = api;
window.toast = toast;
