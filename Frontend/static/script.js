/* ==========================================================================
   Learn2earn shared script. Loaded by every page.

   - API_BASE: the one place the backend address lives. To test against a
     different backend, change it here and nowhere else.
   - Header and footer are built here, so changing the menu is a one-file edit.
   - Staff sign-in, confirmation boxes and pop-up messages are shared.
   ========================================================================== */

const API_BASE = "https://applicant-tracking-system-tbaw.onrender.com";

const L2E = (() => {
  // ---------- Status words: what each saved status is called on screen ----------
  const STATUS = {
    pending:   { label: "Waiting for review", tone: "warn" },
    reviewing: { label: "Being reviewed",     tone: "info" },
    interview: { label: "Interview stage",    tone: "info" },
    accepted:  { label: "Accepted",           tone: "good" },
    rejected:  { label: "Not selected",       tone: "bad"  },
  };
  const statusInfo = (s) => STATUS[String(s || "").toLowerCase()] || { label: String(s || "Unknown"), tone: "muted" };

  // ---------- Small helpers ----------
  // Builds page elements safely. Text is always inserted as text, never as HTML,
  // so nothing a visitor types can run as code.
  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid);
    }
    return node;
  }

  function formatDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
  }

  const WAKE_NOTE = "Waking up the server. The first visit can take up to a minute. Thanks for waiting.";

  // ---------- Talking to the backend ----------
  // onSlow runs once if the server takes more than 4 seconds (the free host sleeps when idle).
  async function request(path, opts = {}) {
    const { method = "GET", body, headers = {}, onSlow, timeoutMs = 70000, cache } = opts;
    const controller = new AbortController();
    const slowTimer = onSlow ? setTimeout(onSlow, 4000) : null;
    const killTimer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const init = { method, headers: { ...headers }, signal: controller.signal };
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      if (cache) init.cache = cache;
      return await fetch(API_BASE + path, init);
    } finally {
      clearTimeout(slowTimer);
      clearTimeout(killTimer);
    }
  }

  async function loadOpenJobs(onSlow) {
    const res = await request("/jobs/?status=approved", { onSlow });
    if (!res.ok) throw new Error("Could not load jobs");
    const data = await res.json();
    return Array.isArray(data) ? data : (data.jobs || []);
  }

  // ---------- Header and footer ----------
  const BRAND_ICON =
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 13h18"/></svg>';

  function mountChrome() {
    const page = document.body.dataset.page || "";
    const staff = document.body.dataset.staff === "true";
    const current = (name) => (page === name ? ' aria-current="page"' : "");

    const header = document.getElementById("site-header");
    if (header) {
      header.innerHTML = staff
        ? `<div class="wrap">
             <a class="brand" href="/admin"><span class="brand-mark">${BRAND_ICON}</span>Learn2earn <span class="badge-staff">Staff</span></a>
             <nav class="nav" aria-label="Main">
               <a href="/admin"${current("admin")}>Jobs and applications</a>
               <a href="/dashboard"${current("dashboard")}>Summary</a>
               <a href="/">Public site</a>
               <button type="button" id="sign-out-btn">Sign out</button>
             </nav>
           </div>`
        : `<div class="wrap">
             <a class="brand" href="/"><span class="brand-mark">${BRAND_ICON}</span>Learn2earn</a>
             <nav class="nav" aria-label="Main">
               <a href="/jobs"${current("jobs")}>Jobs</a>
               <a href="/track"${current("track")}>Check my application</a>
             </nav>
           </div>`;
    }

    const footer = document.getElementById("site-footer");
    if (footer) {
      footer.innerHTML = `<div class="wrap footer-row">
          <p>&copy; ${new Date().getFullYear()} Learn2earn</p>
          <nav aria-label="Footer">
            <a href="/jobs">Jobs</a>
            <a href="/track">Check my application</a>
            <a href="/admin">Staff sign in</a>
          </nav>
        </div>`;
    }

    document.body.append(el("div", { class: "toasts", id: "toasts", role: "status", "aria-live": "polite" }));
  }

  // ---------- Pop-up messages ----------
  function toast(message, tone = "good") {
    const box = document.getElementById("toasts");
    if (!box) return;
    const item = el("div", { class: "toast" + (tone === "bad" ? " toast-bad" : tone === "info" ? " toast-info" : ""), text: message });
    box.append(item);
    setTimeout(() => item.remove(), tone === "bad" ? 8000 : 5000);
  }

  // ---------- "Are you sure?" box ----------
  function confirmBox({ title, message, confirmLabel = "Yes", cancelLabel = "Cancel", danger = false }) {
    return new Promise((resolve) => {
      let answer = false;
      const dialog = el("dialog", { "aria-labelledby": "confirm-title" });
      const yes = el("button", { type: "button", class: "btn " + (danger ? "btn-danger" : "btn-primary"), text: confirmLabel });
      const no = el("button", { type: "button", class: "btn btn-plain", text: cancelLabel });
      yes.addEventListener("click", () => { answer = true; dialog.close(); });
      no.addEventListener("click", () => dialog.close());
      dialog.append(
        el("h2", { id: "confirm-title", text: title }),
        el("p", { text: message }),
        el("div", { class: "dialog-actions" }, no, yes)
      );
      dialog.addEventListener("close", () => { dialog.remove(); resolve(answer); });
      document.body.append(dialog);
      dialog.showModal();
      no.focus();
    });
  }

  // ---------- Staff sign-in (shared by the admin and summary pages) ----------
  // The key is kept for this browser tab only and is cleared when the tab closes.
  let adminKey = "";
  try { adminKey = sessionStorage.getItem("adminKey") || ""; } catch (e) { /* storage blocked */ }
  let onReady = () => {};
  let onSignOut = () => {};

  function setPageLocked(locked) {
    const header = document.querySelector("header");
    const main = document.querySelector("main");
    if (header) header.inert = locked;
    if (main) main.inert = locked;
  }

  function showLogin(message) {
    const overlay = document.getElementById("login-overlay");
    const err = document.getElementById("login-error");
    if (message) { err.textContent = message; err.hidden = false; } else { err.hidden = true; }
    setPageLocked(true);
    overlay.hidden = false;
    document.getElementById("admin-key-input").focus();
  }

  function mountLogin() {
    const input = el("input", { type: "password", id: "admin-key-input", required: true, autocomplete: "current-password" });
    const form = el("form", { class: "panel stack" },
      el("div", {}, el("h2", { id: "login-title", text: "Staff sign in" }), el("p", { class: "muted", text: "Enter the staff access key to manage jobs and applications." })),
      el("div", { class: "field" }, el("label", { for: "admin-key-input", text: "Staff access key" }), input),
      el("p", { id: "login-error", class: "alert alert-bad", role: "alert", hidden: true }),
      el("button", { type: "submit", class: "btn btn-primary btn-block", text: "Sign in" })
    );
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      adminKey = input.value.trim();
      try { sessionStorage.setItem("adminKey", adminKey); } catch (err) { /* storage blocked */ }
      input.value = "";
      overlay.hidden = true;
      setPageLocked(false);
      onReady();
    });
    const overlay = el("div", { id: "login-overlay", class: "overlay", role: "dialog", "aria-modal": "true", "aria-labelledby": "login-title", hidden: true }, form);
    document.body.append(overlay);
  }

  function signOut() {
    adminKey = "";
    try { sessionStorage.removeItem("adminKey"); } catch (err) { /* storage blocked */ }
    onSignOut();
    showLogin();
  }

  // Same as request(), but sends the staff key. A 401 means the key is wrong, so ask again.
  async function adminFetch(path, options = {}) {
    const requestKey = adminKey;
    const response = await request(path, { ...options, headers: { ...(options.headers || {}), "X-Admin-Key": requestKey } });
    // Ignore an old failed request if the person signed out or signed in again.
    if (response.status === 401 && requestKey && requestKey === adminKey) {
      adminKey = "";
      try { sessionStorage.removeItem("adminKey"); } catch (err) { /* storage blocked */ }
      showLogin("That key was not accepted. Check it and try again.");
    }
    return response;
  }

  // Call once from a staff page. ready() loads the page's data; cleared() empties it on sign out.
  function startStaff(ready, cleared) {
    onReady = ready;
    onSignOut = cleared;
    mountLogin();
    document.getElementById("sign-out-btn").addEventListener("click", signOut);
    if (adminKey) ready(); else showLogin();
  }

  const keyIsCurrent = (k) => Boolean(adminKey) && k === adminKey;
  const currentKey = () => adminKey;

  mountChrome();

  return { STATUS, statusInfo, el, formatDate, WAKE_NOTE, request, loadOpenJobs, toast, confirmBox, startStaff, adminFetch, keyIsCurrent, currentKey };
})();
