/* ==========================================================================
   Rolebeam shared script. Loaded by every page.

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
    withdrawn: { label: "Withdrawn",          tone: "muted" },
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
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(iso || ""));
    const d = dateOnly ? new Date(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) : new Date(iso);
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
        if (body instanceof FormData) {
          init.body = body;
        } else {
          init.headers["Content-Type"] = "application/json";
          init.body = JSON.stringify(body);
        }
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
    '<svg width="50" height="50" viewBox="0 0 64 64" fill="none" aria-hidden="true">' +
    '<path d="M17 48V16h14a10 10 0 0 1 0 20H17m14 0 16 12" stroke="currentColor" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M40 21h9M43 28h10M40 35h9" stroke="#91D8FF" stroke-width="3" stroke-linecap="round"/></svg>';
  const BRAND_WORDMARK = '<span class="brand-word"><span class="brand-initial">R</span><span class="brand-name-rest">olebeam</span></span>';

  function mountChrome() {
    const page = document.body.dataset.page || "";
    const staff = document.body.dataset.staff === "true";
    const current = (name) => (page === name ? ' aria-current="page"' : "");

    const header = document.getElementById("site-header");
    if (header) {
      header.innerHTML = staff
        ? `<div class="wrap">
             <a class="brand" href="/admin"><span class="brand-mark">${BRAND_ICON}</span>${BRAND_WORDMARK}<span class="badge-staff">Staff</span></a>
             <nav class="nav" aria-label="Main">
               <a href="/">Public site</a>
               <button type="button" id="sign-out-btn">Sign out</button>
             </nav>
           </div>`
        : `<div class="wrap">
             <a class="brand" href="/"><span class="brand-mark">${BRAND_ICON}</span>${BRAND_WORDMARK}</a>
             <nav class="nav" aria-label="Main">
               <a href="/jobs"${current("jobs")}>Jobs</a>
               <a href="/track"${current("track")}>Check my application</a>
             </nav>
           </div>`;
    }

    const footer = document.getElementById("site-footer");
    if (footer) {
      footer.innerHTML = `<div class="wrap footer-row">
          <p>&copy; ${new Date().getFullYear()} Rolebeam</p>
          <nav aria-label="Footer">
            <a href="/jobs">Jobs</a>
            <a href="/track">Check my application</a>
            <a href="/privacy">Privacy</a>
            <a href="/contact">Contact</a>
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
  // Supabase Auth session is kept in this tab only.
  let staffSession = null;
  try { staffSession = JSON.parse(sessionStorage.getItem("staffSession") || "null"); } catch (e) { staffSession = null; }
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
    document.getElementById("staff-email-input").focus();
  }

  function mountLogin() {
    const emailInput = el("input", { type: "email", id: "staff-email-input", required: true, autocomplete: "username", inputmode: "email" });
    const passwordInput = el("input", { type: "password", id: "staff-password-input", required: true, autocomplete: "current-password" });
    const form = el("form", { class: "panel stack" },
      el("div", {}, el("h2", { id: "login-title", text: "Staff sign in" }), el("p", { class: "muted", text: "Sign in with your approved staff account." })),
      el("div", { class: "field" }, el("label", { for: "staff-email-input", text: "Staff email" }), emailInput),
      el("div", { class: "field" }, el("label", { for: "staff-password-input", text: "Password" }), passwordInput),
      el("p", { id: "login-error", class: "alert alert-bad", role: "alert", hidden: true }),
      el("button", { type: "submit", class: "btn btn-primary btn-block", text: "Sign in" })
    );
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true; button.textContent = "Signing in…";
      try {
        const response = await request("/auth/login", { method: "POST", body: { email: emailInput.value.trim(), password: passwordInput.value } });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Sign-in failed. Check your details and try again.");
        staffSession = { ...data, expires_at: Date.now() + Number(data.expires_in || 3600) * 1000 };
        try { sessionStorage.setItem("staffSession", JSON.stringify(staffSession)); } catch (err) { /* storage blocked */ }
        passwordInput.value = ""; overlay.hidden = true; setPageLocked(false); onReady();
      } catch (error) {
        const errorBox = document.getElementById("login-error");
        errorBox.textContent = error.message || "Could not sign in. Try again."; errorBox.hidden = false;
      } finally { button.disabled = false; button.textContent = "Sign in"; }
    });
    const overlay = el("div", { id: "login-overlay", class: "overlay", role: "dialog", "aria-modal": "true", "aria-labelledby": "login-title", hidden: true }, form);
    document.body.append(overlay);
  }

  function signOut() {
    staffSession = null;
    try { sessionStorage.removeItem("staffSession"); } catch (err) { /* storage blocked */ }
    onSignOut();
    showLogin();
  }

  async function refreshStaffSession() {
    if (!staffSession?.refresh_token) return false;
    const response = await request("/auth/refresh", { method: "POST", body: { refresh_token: staffSession.refresh_token } });
    if (!response.ok) return false;
    const data = await response.json();
    staffSession = { ...data, expires_at: Date.now() + Number(data.expires_in || 3600) * 1000 };
    try { sessionStorage.setItem("staffSession", JSON.stringify(staffSession)); } catch (err) { /* storage blocked */ }
    return true;
  }

  // Staff requests carry a short-lived Supabase access token; refresh it before expiry.
  async function adminFetch(path, options = {}) {
    if (!staffSession?.access_token) { showLogin("Please sign in to continue."); return new Response(null, { status: 401 }); }
    if (Date.now() > Number(staffSession.expires_at || 0) - 60000 && !(await refreshStaffSession())) {
      signOut(); return new Response(null, { status: 401 });
    }
    const response = await request(path, { ...options, headers: { ...(options.headers || {}), Authorization: "Bearer " + staffSession.access_token } });
    if (response.status === 401 && staffSession) { signOut(); }
    return response;
  }

  // Call once from a staff page. ready() loads the page's data; cleared() empties it on sign out.
  function startStaff(ready, cleared) {
    onReady = ready;
    onSignOut = cleared;
    mountLogin();
    document.getElementById("sign-out-btn").addEventListener("click", signOut);
    if (staffSession?.access_token && staffSession?.refresh_token) ready(); else showLogin();
  }

  const keyIsCurrent = (k) => Boolean(staffSession) && k === staffSession.user?.email;
  const currentKey = () => staffSession?.user?.email || "";

  mountChrome();

  return { STATUS, statusInfo, el, formatDate, WAKE_NOTE, request, loadOpenJobs, toast, confirmBox, startStaff, adminFetch, keyIsCurrent, currentKey };
})();
