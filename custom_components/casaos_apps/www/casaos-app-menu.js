// ⋯ menu for an app tile: opens a popup with the app's CasaOS / ZimaOS compose settings (Form or YAML) and saves them
// through the casaos_apps integration. Use it as a picture-elements element:
//   - type: custom:casaos-app-menu
//     server: NAS              # the integration entry's name (or host)
//     container: jellyfin      # container name (or CasaOS app id)
//     style: {top: 8%, left: 90%}
const SECRET = /pass|secret|token|key|pwd|auth|admin|credential/i;
const RESTART = ["no", "always", "on-failure", "unless-stopped"];

const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// Compose allows short and long forms; the form edits the long ones.
function ports(svc) {
  return (svc.ports || []).map((p) => {
    if (typeof p !== "string" && typeof p !== "number") return { target: p.target ?? "", published: p.published ?? "", protocol: p.protocol || "tcp" };
    const [main, protocol = "tcp"] = String(p).split("/");
    const parts = main.split(":");
    return { target: parts.at(-1), published: parts.length > 1 ? parts.at(-2) : "", protocol };
  });
}
function mounts(svc) {
  return (svc.volumes || []).map((v) => {
    if (typeof v !== "string") return { ...v, type: v.type || "bind", source: v.source ?? "", target: v.target ?? "" };
    const [source, target = "", mode] = v.split(":");
    const m = { type: /^[./~]/.test(source) ? "bind" : "volume", source, target };
    if (mode === "ro") m.read_only = true;
    return m;
  });
}
function envs(svc) {
  const e = svc.environment || {};
  if (!Array.isArray(e)) return Object.entries(e).map(([name, value]) => ({ name, value: value ?? "" }));
  return e.map((s) => ({ name: s.split("=")[0], value: s.includes("=") ? s.slice(s.indexOf("=") + 1) : "" }));
}
function devices(svc) {
  return (svc.devices || []).map((d) => (typeof d === "string" ? d : `${d.source}:${d.target}`));
}
function splitImage(image = "") {
  const i = image.lastIndexOf(":");
  return i > image.lastIndexOf("/") ? [image.slice(0, i), image.slice(i + 1)] : [image, "latest"];
}
function memMB(svc) {
  const m = svc.deploy?.resources?.limits?.memory;
  if (m === undefined || m === null || m === "") return "";
  const n = parseFloat(m), unit = String(m).replace(/[\d.\s]/g, "").toLowerCase()[0];
  return Math.round(n * ({ k: 1 / 1024, m: 1, g: 1024 }[unit] ?? 1 / 1048576));
}

class CasaOSAppMenu extends HTMLElement {
  setConfig(config) {
    this._config = config;
  }
  set hass(hass) {
    this._hass = hass;
  }
  connectedCallback() {
    if (!this._done) {
      this._done = true;
      this.title = "Configuración";
      this.textContent = "⋯";
      Object.assign(this.style, { cursor: "pointer", fontSize: "16px", fontWeight: "700", lineHeight: "1", padding: "2px 6px",
                                  color: "var(--secondary-text-color)", userSelect: "none", transition: "opacity .15s" });
      this.addEventListener("click", (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        new CasaOSAppDialog(this._hass, this._config).open();
      });
    }
    // Hidden until the pointer is over this tile; touch screens have no hover, so there it always shows.
    // Checked on every connect: the tile can be attached in steps, so its card isn't always there the first time.
    const tile = this.getRootNode().host;
    if (!tile || tile === this._tile || !matchMedia("(hover: hover)").matches) return;
    this._tile = tile;
    this.style.opacity = tile.matches(":hover") ? "1" : "0";
    tile.addEventListener("mouseenter", () => (this.style.opacity = "1"));
    tile.addEventListener("mouseleave", () => (this.style.opacity = "0"));
  }
}

class CasaOSAppDialog {
  constructor(hass, config) {
    this.hass = hass;
    this.cfg = config;
    this.tab = "form";
    this.svcName = null;
    this.advanced = false;
    this.dirty = false;
  }

  ws(msg) {
    return this.hass.callWS(msg);
  }

  async open() {
    this.host = document.createElement("div");
    this.root = this.host.attachShadow({ mode: "open" });
    document.body.appendChild(this.host);
    this.onKey = (e) => e.key === "Escape" && this.close();
    document.addEventListener("keydown", this.onKey);
    this.frame(`<div class="msg">Cargando…</div>`);
    try {
      const r = await this.ws({ type: "casaos_apps/app", server: this.cfg.server, container: this.cfg.container });
      Object.assign(this, { appId: r.app_id, srvHost: r.host, compose: r.compose, yaml: r.yaml, readonly: r.readonly });
      const x = this.compose["x-casaos"] || {};
      this.svcName = x.main && this.compose.services?.[x.main] ? x.main : Object.keys(this.compose.services || {})[0];
      this.render();
    } catch (e) {
      this.frame(`<div class="err">${esc(e.message || e)}</div>`);
    }
  }

  close(force) {
    if (!force && this.dirty && !confirm("Hay cambios sin guardar. ¿Cerrar igualmente?")) return;
    document.removeEventListener("keydown", this.onKey);
    this.host.remove();
  }

  get x() {
    return (this.compose["x-casaos"] ||= {});
  }
  get svc() {
    return this.compose.services[this.svcName];
  }
  get titleText() {
    const t = this.x.title || {};
    return t.custom || t.en_us || this.appId || this.cfg.container;
  }

  frame(body) {
    const icon = this.compose && (this.x.icon || this.svc?.labels?.icon);
    this.root.innerHTML = `<style>${CSS}</style>
      <div class="overlay"></div>
      <div class="panel${this.full ? " full" : ""}" role="dialog" aria-label="Configuración">
        <div class="head">
          ${icon ? `<img src="${esc(icon)}" alt="">` : ""}
          <div class="ttl">${esc(this.compose ? `${this.readonly ? "Ver" : "Editar"} ${this.titleText}` : this.cfg.container)}</div>
          ${this.compose ? `<div class="tabs"><button data-tab="form" class="${this.tab === "form" ? "on" : ""}">Form</button><button data-tab="yaml" class="${this.tab === "yaml" ? "on" : ""}">YAML</button></div>` : ""}
          ${this.compose ? `<button class="ico copy" title="Copiar YAML">⧉</button><button class="ico full" title="Pantalla completa">${this.full ? "🗗" : "⛶"}</button>` : ""}
          ${this.srvHost ? `<a class="ico" href="http://${esc(this.srvHost)}/" target="_blank" rel="noopener" title="Abrir en ZimaOS / CasaOS">↗</a>` : ""}
          <button class="ico close" title="Cerrar">✕</button>
        </div>
        <div class="body">${body}</div>
        ${this.compose ? `<div class="foot"><div class="status">${this.readonly ? "Creado con «docker run», no lo gestiona ZimaOS / CasaOS: solo lectura (datos de Portainer)." : ""}</div>${this.readonly ? "" : `<button class="save">Guardar</button>`}</div>` : ""}
      </div>`;
    this.root.querySelector(".overlay").onclick = () => this.close();
    this.root.querySelector(".close").onclick = () => this.close();
    this.root.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => this.switchTab(b.dataset.tab)));
    const full = this.root.querySelector(".full");
    if (full) full.onclick = () => { this.keepForm(); this.full = !this.full; this.render(); };
    const copy = this.root.querySelector(".copy");
    if (copy) copy.onclick = () => this.copy();
    const save = this.root.querySelector(".save");
    if (save) save.onclick = () => this.save();
  }

  status(text, err) {
    const s = this.root.querySelector(".status");
    s.textContent = text;
    s.className = "status" + (err ? " bad" : "");
  }

  keepForm() {
    const ta = this.root.querySelector("textarea");
    if (ta) this.yaml = ta.value;  // a re-render must not drop what was typed in the YAML tab
  }

  async copy() {
    try {
      const ta = this.root.querySelector("textarea");
      const text = ta ? ta.value : (await this.ws({ type: "casaos_apps/convert", compose: this.compose })).yaml;
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {  // plain http (e.g. http://<ip>:8123): no Clipboard API
        const t = document.createElement("textarea");
        t.value = text;
        document.body.appendChild(t);
        t.select();
        document.execCommand("copy");
        t.remove();
      }
      this.status("YAML copiado.");
    } catch (e) {
      this.status(`No se pudo copiar: ${e.message || e}`, true);
    }
  }

  async switchTab(tab) {
    if (tab === this.tab) return;
    try {
      if (tab === "yaml") this.yaml = (await this.ws({ type: "casaos_apps/convert", compose: this.compose })).yaml;
      else this.compose = (await this.ws({ type: "casaos_apps/convert", yaml: this.root.querySelector("textarea").value })).compose;
    } catch (e) {
      this.status(`YAML no válido: ${e.message}`, true);
      return;
    }
    this.tab = tab;
    if (!this.compose.services?.[this.svcName]) this.svcName = Object.keys(this.compose.services || {})[0];
    this.render();
  }

  async save() {
    if (!confirm(`¿Guardar y aplicar los cambios? ${this.titleText} se va a recrear (unos segundos sin servicio).`)) return;
    const btn = this.root.querySelector(".save");
    btn.disabled = true;
    this.status("Comprobando y aplicando…");
    try {
      const content = this.tab === "yaml" ? { yaml: this.root.querySelector("textarea").value } : { compose: this.compose };
      await this.ws({ type: "casaos_apps/save", server: this.cfg.server, app_id: this.appId, ...content });
      this.dirty = false;
      this.status("Guardado. Se está recreando el contenedor.");
      setTimeout(() => this.close(true), 1800);
    } catch (e) {
      this.status(e.message || String(e), true);
      btn.disabled = false;
    }
  }

  render() {
    if (this.tab === "yaml") {
      this.frame(`<textarea spellcheck="false">${esc(this.yaml)}</textarea>`);
      this.root.querySelector("textarea").oninput = () => (this.dirty = true);
      this.lock();
      return;
    }
    const s = this.svc, x = this.x;
    const [img, tag] = splitImage(s.image);
    const nets = Object.keys(this.compose.networks || {});
    const mode = s.network_mode || (s.networks ? "" : "bridge");
    const P = ports(s), M = mounts(s), E = envs(s), D = devices(s);
    const opt = (list, v) => [...new Set([v, ...list])].filter((o) => o !== undefined).map((o) => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("");
    const row = (label, input) => `<label class="row"><span>${label}</span>${input}</label>`;
    this.frame(`
      <div class="card">
        ${row("Título", `<input data-k="title" value="${esc(this.titleText)}">`)}
        ${row("Web", `<div class="url"><select data-k="scheme">${opt(["http", "https"], x.scheme || "http")}</select>
            <input data-k="hostname" placeholder="${esc(this.srvHost)}" value="${esc(x.hostname)}">
            <input data-k="port_map" class="short" placeholder="puerto" value="${esc(x.port_map)}">
            <input data-k="index" class="short" placeholder="/" value="${esc(x.index)}"></div>`)}
      </div>
      <div class="sub">Servicios</div>
      <div class="chips">${Object.keys(this.compose.services).map((n) => `<button data-svc="${esc(n)}" class="${n === this.svcName ? "on" : ""}">${esc(n)}</button>`).join("")}</div>
      <div class="card">
        ${row("Contenedor", `<input data-k="container_name" value="${esc(s.container_name)}">`)}
        ${row("Imagen", `<input data-k="image" value="${esc(img)}">`)}
        ${row("Tag", `<input data-k="tag" value="${esc(tag)}">`)}
        ${row("Reinicio", `<select data-k="restart">${opt(RESTART, s.restart || "no")}</select>`)}
        ${row("Red", `<select data-k="network_mode">${opt(["bridge", "host", ...nets], mode)}</select>`)}
      </div>
      ${mode === "host" ? `<div class="note">Con red «host» el contenedor usa los puertos del servidor directamente; no hay redirección de puertos.</div>` : this.table("Puertos", "ports", ["Contenedor", "Servidor", "Protocolo"], P,
        (p, i) => `<input data-t="ports" data-i="${i}" data-f="target" value="${esc(p.target)}"><input data-t="ports" data-i="${i}" data-f="published" value="${esc(p.published)}"><select data-t="ports" data-i="${i}" data-f="protocol">${opt(["tcp", "udp"], p.protocol)}</select>`)}
      ${this.table("Carpetas", "volumes", ["Tipo", "Servidor", "Contenedor"], M,
        (m, i) => `<select data-t="volumes" data-i="${i}" data-f="type">${opt(["bind", "volume", "tmpfs"], m.type)}</select><input data-t="volumes" data-i="${i}" data-f="source" value="${esc(m.source)}"><input data-t="volumes" data-i="${i}" data-f="target" value="${esc(m.target)}">`)}
      ${this.table("Variables", "environment", ["Nombre", "Valor"], E,
        (e, i) => `<input data-t="environment" data-i="${i}" data-f="name" value="${esc(e.name)}"><input data-t="environment" data-i="${i}" data-f="value" ${SECRET.test(e.name) ? 'type="password"' : ""} value="${esc(e.value)}">`)}
      <label class="adv"><input type="checkbox" class="advsw" ${this.advanced ? "checked" : ""}> Avanzado</label>
      ${this.advanced ? `
        ${this.table("Dispositivos", "devices", ["Servidor:Contenedor"], D, (d, i) => `<input data-t="devices" data-i="${i}" value="${esc(d)}">`)}
        <div class="card">
          ${row("CPU (cpu_shares)", `<input data-k="cpu_shares" type="number" value="${esc(s.cpu_shares)}">`)}
          ${row("Memoria máx. (MB)", `<input data-k="memory" type="number" value="${esc(memMB(s))}">`)}
          ${row("Privilegiado", `<input data-k="privileged" type="checkbox" ${s.privileged ? "checked" : ""}>`)}
          ${row("Capacidades (cap_add)", `<input data-k="cap_add" value="${esc((s.cap_add || []).join(", "))}">`)}
          ${row("Comando", `<input data-k="command" value="${esc(Array.isArray(s.command) ? (s.command.length ? JSON.stringify(s.command) : "") : s.command)}">`)}
        </div>` : ""}`);
    this.bind(P, M, E, D);
    this.lock();
  }

  lock() {
    if (!this.readonly) return;
    this.root.querySelectorAll(".body input, .body select, textarea").forEach((el) => {
      if (el.classList.contains("advsw")) return;  // the Advanced switch still shows/hides
      el.tagName === "TEXTAREA" || el.type === "text" || el.type === "number" || !el.type ? (el.readOnly = true) : (el.disabled = true);
      if (el.tagName === "SELECT") el.disabled = true;
    });
    this.root.querySelectorAll(".add, .del").forEach((b) => (b.style.display = "none"));
  }

  table(title, key, cols, rows, cells) {
    return `<div class="sub">${title}<button class="add" data-add="${key}" title="Añadir">＋</button></div>
      <div class="card tbl" style="--cols:${cols.length}">
        ${rows.length ? `<div class="thead">${cols.map((c) => `<span>${c}</span>`).join("")}<span></span></div>` : `<div class="empty">—</div>`}
        ${rows.map((r, i) => `<div class="tr">${cells(r, i)}<button class="del" data-del="${key}" data-i="${i}" title="Quitar">−</button></div>`).join("")}
      </div>`;
  }

  bind(P, M, E, D) {
    const s = this.svc, x = this.x, R = this.root;
    const lists = { ports: P, volumes: M, environment: E, devices: D };
    const write = (k) => {
      if (k === "ports") s.ports = P.map((p) => ({ target: Number(p.target) || p.target, published: String(p.published), protocol: p.protocol }));
      if (k === "volumes") s.volumes = M;
      if (k === "environment") s.environment = Object.fromEntries(E.filter((e) => e.name).map((e) => [e.name, e.value]));
      if (k === "devices") s.devices = D.filter(Boolean);
      for (const f of ["ports", "volumes", "devices"]) if (Array.isArray(s[f]) && !s[f].length) delete s[f];
      this.dirty = true;
    };
    const set = (k, v) => {
      const [img, tag] = splitImage(s.image);
      if (k === "title") (x.title ||= {}).custom = v;
      else if (["scheme", "hostname", "port_map", "index"].includes(k)) x[k] = v;
      else if (k === "image") s.image = `${v}:${tag}`;
      else if (k === "tag") s.image = `${img}:${v || "latest"}`;
      else if (k === "network_mode") (v === "bridge" && !s.network_mode ? null : (s.network_mode = v));
      else if (k === "cpu_shares") v === "" ? delete s.cpu_shares : (s.cpu_shares = Number(v));
      else if (k === "memory") ((((s.deploy ||= {}).resources ||= {}).limits ||= {}).memory = v === "" ? undefined : String(Math.round(v * 1048576)));
      else if (k === "privileged") s.privileged = v;
      else if (k === "cap_add") s.cap_add = v.split(",").map((c) => c.trim()).filter(Boolean);
      else if (k === "command") s.command = v.trim().startsWith("[") ? JSON.parse(v) : v;
      else s[k] = v;
      this.dirty = true;
    };
    R.querySelectorAll("[data-k]").forEach((el) => {
      el.onchange = el.oninput = () => {
        try { set(el.dataset.k, el.type === "checkbox" ? el.checked : el.value); } catch { /* half-typed command JSON */ }
        if (el.dataset.k === "network_mode") this.render();
      };
    });
    R.querySelectorAll("[data-t]").forEach((el) => {
      el.onchange = el.oninput = () => {
        const list = lists[el.dataset.t], i = +el.dataset.i;
        if (el.dataset.f) list[i][el.dataset.f] = el.value;
        else list[i] = el.value;
        write(el.dataset.t);
      };
      if (el.type === "password") { el.onfocus = () => (el.type = "text"); el.onblur = () => (el.type = "password"); }
    });
    R.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => {
      const k = b.dataset.add;
      lists[k].push({ ports: { target: "", published: "", protocol: "tcp" }, volumes: { type: "bind", source: "", target: "" }, environment: { name: "", value: "" }, devices: "" }[k]);
      write(k);
      this.render();
    }));
    R.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => {
      lists[b.dataset.del].splice(+b.dataset.i, 1);
      write(b.dataset.del);
      this.render();
    }));
    R.querySelectorAll("[data-svc]").forEach((b) => (b.onclick = () => { this.svcName = b.dataset.svc; this.render(); }));
    const adv = R.querySelector(".advsw");
    adv.onchange = () => { this.advanced = adv.checked; this.render(); };
  }
}

const CSS = `
  :host { all: initial; }
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 9998; }
  .panel { position: fixed; z-index: 9999; top: 50%; left: 50%; transform: translate(-50%,-50%); width: min(560px, calc(100vw - 32px));
    max-height: min(80vh, 760px); display: flex; flex-direction: column; background: var(--card-background-color, #1c1c1c);
    color: var(--primary-text-color, #e1e1e1); border-radius: var(--ha-card-border-radius, 12px); box-shadow: 0 8px 32px rgba(0,0,0,.45);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif)); font-size: 14px; }
  .panel.full { width: 100vw; height: 100vh; max-height: none; border-radius: 0; }
  .panel.full textarea { min-height: calc(100vh - 150px); }
  .head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--divider-color, #333); }
  .head img { width: 28px; height: 28px; border-radius: 6px; object-fit: contain; }
  .ttl { flex: 1; font-size: 16px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tabs { display: flex; background: var(--secondary-background-color, #2a2a2a); border-radius: 8px; padding: 2px; }
  .tabs button, .chips button { border: 0; background: none; color: var(--secondary-text-color, #9b9b9b); padding: 4px 10px; border-radius: 6px; cursor: pointer; font: inherit; }
  .tabs button.on, .chips button.on { background: var(--card-background-color, #1c1c1c); color: var(--primary-text-color, #e1e1e1); }
  .ico { border: 0; background: none; color: var(--secondary-text-color, #9b9b9b); cursor: pointer; font-size: 16px; text-decoration: none; padding: 2px 4px; }
  .body { overflow: auto; padding: 10px 14px; flex: 1; }
  .card { background: var(--secondary-background-color, #2a2a2a); border-radius: 10px; padding: 6px 10px; margin-bottom: 8px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
  .row > span { flex: 0 0 38%; color: var(--secondary-text-color, #9b9b9b); }
  .row > input, .row > select, .url { flex: 1; min-width: 0; }
  .row > input[type=checkbox] { flex: 0 0 auto; }
  .url { display: flex; gap: 4px; }
  .url input { flex: 1; min-width: 0; } .url .short { flex: 0 0 56px; } .url select { flex: 0 0 auto; }
  input, select, textarea { box-sizing: border-box; background: var(--card-background-color, #1c1c1c); color: var(--primary-text-color, #e1e1e1);
    border: 1px solid var(--divider-color, #3a3a3a); border-radius: 6px; padding: 5px 7px; font: inherit; font-size: 13px; }
  input:focus, select:focus, textarea:focus { outline: none; border-color: var(--primary-color, #03a9f4); }
  .sub { display: flex; align-items: center; justify-content: space-between; margin: 10px 2px 4px; font-weight: 500; color: var(--secondary-text-color, #9b9b9b); font-size: 13px; }
  .chips { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
  .chips button { background: var(--secondary-background-color, #2a2a2a); }
  .tbl .thead, .tbl .tr { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)) 24px; gap: 4px; align-items: center; padding: 2px 0; }
  .tbl .thead span { font-size: 12px; color: var(--secondary-text-color, #9b9b9b); }
  .tbl input, .tbl select { width: 100%; }
  .add, .del { border: 0; background: none; color: var(--secondary-text-color, #9b9b9b); cursor: pointer; font-size: 16px; padding: 0 4px; }
  .add { color: var(--primary-color, #03a9f4); }
  .empty { color: var(--secondary-text-color, #9b9b9b); padding: 4px 0; }
  .note { font-size: 12px; color: var(--secondary-text-color, #9b9b9b); padding: 4px 2px 8px; }
  .adv { display: flex; align-items: center; gap: 6px; margin: 10px 2px; color: var(--secondary-text-color, #9b9b9b); cursor: pointer; }
  textarea { width: 100%; min-height: 55vh; font-family: ui-monospace, Consolas, monospace; font-size: 12px; line-height: 1.45; resize: vertical; white-space: pre; tab-size: 2; }
  .foot { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--divider-color, #333); }
  .status { flex: 1; font-size: 12px; color: var(--secondary-text-color, #9b9b9b); white-space: pre-wrap; max-height: 90px; overflow: auto; }
  .status.bad, .err { color: var(--error-color, #db4437); }
  .save { border: 0; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); padding: 7px 18px; border-radius: 8px; cursor: pointer; font: inherit; font-weight: 500; }
  .save:disabled { opacity: .5; cursor: default; }
  .msg, .err { padding: 18px 4px; }
`;

customElements.define("casaos-app-menu", CasaOSAppMenu);
