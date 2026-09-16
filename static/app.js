/* ============================================================
   MineraAI — SPA (JS puro, sem build)
   Módulos: Dashboard · Radar Viral · Produtos · Criadores ·
            Lives · Nichos · Estúdio IA · Biblioteca · APIs
   ============================================================ */

// ------------------------------------------------------------------ utils
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// JSON seguro para dentro de atributos on*='' (apóstrofos viram entidade)
const jattr = (x) => JSON.stringify(x).replace(/'/g, "&#39;");

function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(".0", "") + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(".0", "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(".0", "") + "K";
  return String(Math.round(n));
}
const fmtBRL = (n) => "R$ " + fmtNum(n);
const fmtDur = (s) => {
  if (!s) return "";
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${s}s`;
};
const timeAgoH = (h) => h < 24 ? `${Math.round(h)}h atrás` : `${Math.round(h / 24)}d atrás`;

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
}

function toast(msg, isErr = false) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 3400);
}

async function copyText(txt, label = "Copiado!") {
  try { await navigator.clipboard.writeText(txt); toast(label); }
  catch { toast("Não foi possível copiar", true); }
}

// ------------------------------------------------------------------ visuais reutilizáveis
const PF_META = {
  tiktok: { label: "TikTok", color: "#22d3ee", grad: ["#0ea5b7", "#155e75"] },
  instagram: { label: "Instagram", color: "#f472b6", grad: ["#be185d", "#7e22ce"] },
  youtube: { label: "YouTube", color: "#f87171", grad: ["#b91c1c", "#7f1d1d"] },
};
const pfBadge = (p) => `<span class="pf" style="color:${PF_META[p]?.color}">▸ ${PF_META[p]?.label || p}</span>`;

function scoreRing(score, size = 42) {
  const r = (size - 8) / 2, c = 2 * Math.PI * r;
  const col = score >= 75 ? "#f0b429" : score >= 50 ? "#34d399" : "#8b94a8";
  return `<svg class="score-ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="rgba(0,0,0,.55)" stroke="#2a3450" stroke-width="3.5"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${col}" stroke-width="3.5"
      stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - score / 100)}" stroke-linecap="round"/>
    <text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" font-size="12"
      font-weight="800" fill="#fff" transform="rotate(90 ${size / 2} ${size / 2})">${score}</text>
  </svg>`;
}

function sparkline(data, w = 110, h = 30, color = "#f0b429") {
  if (!data?.length) return "";
  const max = Math.max(...data), min = Math.min(...data);
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - 2 - ((v - min) / Math.max(max - min, 1)) * (h - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" width="${w}" height="${h}">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
  </svg>`;
}

function areaChart(data, color = "#f0b429", h = 90) {
  const w = 560;
  const max = Math.max(...data), min = Math.min(...data);
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * w,
    h - 6 - ((v - min) / Math.max(max - min, 1)) * (h - 18),
  ]);
  const line = pts.map(p => p.join(",")).join(" ");
  const area = `0,${h} ` + line + ` ${w},${h}`;
  return `<svg width="100%" viewBox="0 0 ${w} ${h}" style="max-width:${w}px">
    <polygon points="${area}" fill="${color}22"/>
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round"/>
  </svg>`;
}

function skeletonGrid(n = 6, hgt = 230) {
  return `<div class="vid-grid">${Array.from({ length: n },
    () => `<div class="skeleton" style="height:${hgt}px"></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ estado global
const state = { status: null, lastSearch: null };

async function loadStatus() {
  try {
    state.status = await api("/status");
    const live = state.status.live.length;
    $("#modePill").innerHTML = live
      ? `Modo <b>híbrido</b> — ${live} API(s) oficial(is) conectada(s).`
      : `Modo <b>demonstração</b> — dados simulados. Conecte suas chaves em <b>APIs & Conexões</b>.`;
  } catch { $("#modePill").textContent = "Backend offline"; }
}

// ------------------------------------------------------------------ salvar na biblioteca
async function saveToLibrary(kind, ref, title, payload) {
  try {
    await api("/library", { method: "POST", body: { kind, ref, title, payload } });
    toast("Salvo na biblioteca 📁");
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ modal
function openModal(html) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-back" onclick="if(event.target===this)closeModal()">
    <div class="modal"><button class="close-x" onclick="closeModal()">×</button>${html}</div></div>`;
}
window.closeModal = () => { $("#modal-root").innerHTML = ""; };

// ============================================================ VÍDEO CARD
function videoCard(v) {
  const meta = PF_META[v.platform] || PF_META.tiktok;
  const grad = `linear-gradient(135deg, ${meta.grad[0]}cc, ${meta.grad[1]}ee)`;
  return `<div class="card vid-card">
    <div class="thumb" style="background:${grad}">
      ${pfBadge(v.platform)}
      <div class="score" title="Viral Score">${scoreRing(v.viral_score)}</div>
      ${v.duration ? `<span class="duration">${fmtDur(v.duration)}</span>` : ""}
    </div>
    <div class="vid-body">
      <div class="vid-title">${esc(v.title)}</div>
      <div class="vid-author">${esc(v.handle || v.author)} · ${timeAgoH(v.age_hours)}
        <span class="src-badge src-${v.source}">${v.source === "oficial" ? "oficial" : "demo"}</span></div>
      <div class="vid-metrics">
        <span>👁 <b>${fmtNum(v.views)}</b></span>
        <span>❤ <b>${fmtNum(v.likes)}</b></span>
        <span>💬 <b>${fmtNum(v.comments)}</b></span>
        <span>⚡ <b>${v.engagement}%</b></span>
      </div>
      ${v.hashtags?.length ? `<div class="tags-row">${v.hashtags.slice(0, 4)
        .map(t => `<span class="mini-tag">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="vid-actions">
        <button class="btn small" onclick='saveToLibrary("video", ${jattr(v.id)}, ${jattr(v.title)}, ${jattr(v)})'>📁 Salvar</button>
        <button class="btn small" onclick='goToLab(${jattr(v.title)})'>🧪 Analisar</button>
        ${v.url ? `<a class="btn small ghost" href="${esc(v.url)}" target="_blank" rel="noopener">↗ Abrir</a>` : ""}
      </div>
    </div>
  </div>`;
}
window.goToLab = (subject) => {
  location.hash = "#/studio";
  setTimeout(() => { switchStudioTab("lab"); $("#lab-subject").value = subject; }, 120);
};

// ============================================================ ROTAS
const routes = {
  dashboard: viewDashboard,
  radar: viewRadar,
  produtos: viewProdutos,
  criadores: viewCriadores,
  lives: viewLives,
  nichos: viewNichos,
  studio: viewStudio,
  biblioteca: viewBiblioteca,
  apis: viewApis,
};

function router() {
  const route = (location.hash || "#/dashboard").replace("#/", "") || "dashboard";
  const [name] = route.split("/");
  $$(".nav a").forEach(a => a.classList.toggle("active", a.dataset.route === name));
  const view = routes[name] || viewDashboard;
  view().catch(e => { $("#view").innerHTML = `<div class="empty">Erro: ${esc(e.message)}</div>`; });
}

// ============================================================ DASHBOARD
async function viewDashboard() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Dashboard ⛏️</h1>
      <p>O garimpo do dia: produtos quentes, lives faturando e nichos emergentes — tudo em um só painel.</p>
    </div></div>
    <div class="grid cols-4" id="kpis"></div>
    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>📦 Top produtos (GMV est. 30d)</h3><div id="dash-products">…</div></div>
      <div class="card"><h3>🔴 Lives faturando agora</h3><div id="dash-lives">…</div></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>🧭 Nichos com maior outlier score</h3><div id="dash-niches">…</div></div>`;

  const [prod, lives, niches] = await Promise.all([
    api("/products?limit=6&sort=gmv"), api("/lives?limit=5"), api("/niches?limit=5"),
  ]);

  const avgGrowth = prod.products.reduce((s, p) => s + p.growth, 0) / Math.max(prod.products.length, 1);
  $("#kpis").innerHTML = `
    ${kpi("GMV total garimpado", fmtBRL(prod.total_gmv), "soma dos top produtos · 30 dias")}
    ${kpi("Crescimento médio", (avgGrowth >= 0 ? "+" : "") + avgGrowth.toFixed(1) + "%",
      "variação dos produtos em alta", avgGrowth >= 0 ? "var(--green)" : "var(--red)")}
    ${kpi("Lives ativas", lives.ao_vivo_agora, `${fmtBRL(lives.gmv_total)} em GMV no painel`, "var(--red)")}
    ${kpi("Nicho mais quente", niches.niches[0]?.outlier_score + " pts", niches.niches[0]?.niche || "", "var(--violet)")}`;

  $("#dash-products").innerHTML = `<table class="table"><tbody>${prod.products.map((p, i) => `
    <tr class="click" onclick="openProduct('${p.id}')">
      <td class="num" style="color:var(--faint)">${i + 1}</td>
      <td><b>${esc(p.name)}</b><br><small style="color:var(--muted)">${p.category}</small></td>
      <td class="num">${fmtBRL(p.gmv)}</td>
      <td>${p.growth >= 0 ? `<span class="pos">▲ ${p.growth}%</span>` : `<span class="neg">▼ ${Math.abs(p.growth)}%</span>`}</td>
      <td>${sparkline(p.curve)}</td>
    </tr>`).join("")}</tbody></table>`;

  $("#dash-lives").innerHTML = lives.lives.map(l => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px dashed var(--line-soft)">
      <div><b>@${esc(l.host)}</b> <small style="color:var(--muted)">· ${esc(l.product)}</small><br>
      <small style="color:var(--muted)">${PF_META[l.platform].label} · pico ${fmtNum(l.viewers_peak)} viewers</small></div>
      <div style="text-align:right">${l.live_now ? '<span class="badge red pulse"><span class="dot"></span>AO VIVO</span>' : ""}
      <div class="num" style="margin-top:4px">${fmtBRL(l.gmv)}</div></div>
    </div>`).join("");

  $("#dash-niches").innerHTML = `<table class="table"><tbody>${niches.niches.map(n => `
    <tr>
      <td><b>${esc(n.niche)}</b><br><small style="color:var(--muted)">${n.sub_nicho}</small></td>
      <td class="num">${fmtNum(n.views_por_video)}<br><small style="color:var(--muted)">views/vídeo</small></td>
      <td class="num">${n.videos}<br><small style="color:var(--muted)">vídeos</small></td>
      <td style="min-width:140px">
        <div style="display:flex;align-items:center;gap:8px">
          <div style="flex:1;height:8px;background:var(--panel-2);border-radius:99px;overflow:hidden">
            <div style="width:${n.outlier_score}%;height:100%;background:linear-gradient(90deg,#8b7cf6,#f0b429)"></div>
          </div><b>${n.outlier_score}</b>
        </div>
      </td>
      <td><span class="badge ${n.status === "QUENTE" ? "red" : "violet"}">${n.status}</span></td>
    </tr>`).join("")}</tbody></table>`;
}
const kpi = (label, value, sub, color = "var(--gold)") =>
  `<div class="card kpi"><span class="label">${label}</span>
   <span class="value" style="color:${color}">${value}</span><span class="sub">${sub}</span></div>`;

// ============================================================ RADAR VIRAL
async function viewRadar() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Radar Viral 🔎</h1>
      <p>Pesquise por palavra-chave em TikTok, Instagram e YouTube ao mesmo tempo.
      Encontre vídeos em alta, hashtags, sons e criadores dominando o tema — e replique o formato.</p>
    </div></div>
    <div class="card">
      <div class="form-row">
        <div class="grow"><input id="radar-q" placeholder="ex: garrafa térmica, skincare, mistérios…" value="achadinhos de casa" /></div>
        <select id="radar-pf" style="width:170px">
          <option value="all">Todas as redes</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
          <option value="youtube">YouTube</option>
        </select>
        <select id="radar-period" style="width:130px">
          <option value="24h">Últimas 24h</option><option value="7d">7 dias</option>
          <option value="30d" selected>30 dias</option><option value="90d">90 dias</option>
        </select>
        <select id="radar-sort" style="width:170px">
          <option value="viral_score">Viral score</option><option value="views">Views</option>
          <option value="likes">Likes</option><option value="engagement">Engajamento</option>
          <option value="recent">Mais recentes</option>
        </select>
        <button class="btn primary" id="radar-go">⚡ Garimpar</button>
      </div>
    </div>
    <div id="radar-summary" style="margin-top:14px"></div>
    <div style="display:grid;grid-template-columns:1fr 300px;gap:14px;margin-top:14px" class="radar-layout">
      <div id="radar-results">${skeletonGrid(6)}</div>
      <div>
        <div class="card"><h3># Hashtags dominantes</h3><div id="radar-tags">…</div></div>
        <div class="card" style="margin-top:14px"><h3>🎵 Sons em alta</h3><div id="radar-sounds">…</div></div>
        <div class="card" style="margin-top:14px"><h3>👤 Criadores no tema</h3><div id="radar-creators">…</div></div>
      </div>
    </div>`;
  $("#radar-go").onclick = runRadar;
  $("#radar-q").addEventListener("keydown", e => { if (e.key === "Enter") runRadar(); });
  if (state.lastSearch) runRadar(state.lastSearch); else runRadar();
}

async function runRadar(saved) {
  const q = $("#radar-q").value.trim() || "tendências";
  const params = new URLSearchParams({
    q, platform: $("#radar-pf").value, period: $("#radar-period").value,
    sort: $("#radar-sort").value, limit: "12",
  });
  state.lastSearch = { q };
  $("#radar-results").innerHTML = skeletonGrid(6);
  const data = await api("/search?" + params);
  const { source_breakdown: sb } = data;
  $("#radar-summary").innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <span class="badge gold">${data.total} vídeos encontrados</span>
      <span class="badge green">oficial: ${sb.oficial}</span>
      <span class="badge violet">demo: ${sb.demo}</span>
      ${sb.oficial === 0 ? '<small style="color:var(--muted)">— conecte suas chaves em <span class="link-gold" onclick="location.hash=&quot;#/apis&quot;">APIs & Conexões</span> para dados reais</small>' : ""}
    </div>`;
  $("#radar-results").innerHTML = data.videos.length
    ? `<div class="vid-grid">${data.videos.map(videoCard).join("")}</div>`
    : `<div class="empty">Nenhum resultado. Tente outro termo.</div>`;
  $("#radar-tags").innerHTML = data.top_hashtags.map(t => `
    <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:13px">
      <b style="color:var(--cyan)">${esc(t.tag)}</b><span class="num">${fmtNum(t.reach)}</span></div>`).join("") || "—";
  $("#radar-sounds").innerHTML = data.top_sounds.map(s => `
    <div style="padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:12.5px">
      🎵 ${esc(s.sound)}<br><small class="num" style="color:var(--muted)">alcance ${fmtNum(s.reach)}</small></div>`).join("") || "—";
  $("#radar-creators").innerHTML = data.top_creators.map(c => `
    <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:13px">
      <b>${esc(c.handle)}</b><span class="num" style="color:var(--muted)">${c.videos} víd · ${fmtNum(c.views)}</span></div>`).join("") || "—";
}

// ============================================================ PRODUTOS
let prodCat = "";
async function viewProdutos() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Produtos 📦</h1>
      <p>Ranking de produtos com GMV estimado, unidades vendidas, crescimento e comissões —
      filtre por categoria e encontre o próximo vencedor.</p>
    </div><button class="btn" onclick="viewProdutos()">↻ Atualizar</button></div>
    <div class="card">
      <div class="form-row">
        <div class="grow"><input id="prod-q" placeholder="Buscar produto ou palavra-chave…" /></div>
        <select id="prod-sort" style="width:180px">
          <option value="gmv">Maior GMV</option><option value="units">Mais vendidos</option>
          <option value="growth">Maior crescimento</option><option value="commission">Maior comissão</option>
        </select>
        <button class="btn primary" id="prod-go">Buscar</button>
      </div>
      <div class="form-row" style="margin-top:12px" id="prod-cats"></div>
    </div>
    <div class="card" style="margin-top:14px"><div id="prod-table">…</div>
    <small style="color:var(--faint)">Valores estimados por modelo público (views × conversão × ticket médio). Não são números oficiais das plataformas.</small></div>`;
  const cats = await api("/products?limit=1");
  $("#prod-cats").innerHTML = `<button class="chip active" data-c="">Todas</button>` +
    cats.categories.map(c => `<button class="chip" data-c="${c}">${c}</button>`).join("");
  $$("#prod-cats .chip").forEach(ch => ch.onclick = () => {
    $$("#prod-cats .chip").forEach(x => x.classList.remove("active"));
    ch.classList.add("active"); prodCat = ch.dataset.c; loadProducts();
  });
  $("#prod-go").onclick = loadProducts;
  $("#prod-q").addEventListener("keydown", e => { if (e.key === "Enter") loadProducts(); });
  loadProducts();
}

async function loadProducts() {
  $("#prod-table").innerHTML = skeletonGrid(3, 70);
  const params = new URLSearchParams({ sort: $("#prod-sort").value, limit: "18" });
  const q = $("#prod-q").value.trim();
  if (q) params.set("q", q);
  if (prodCat) params.set("category", prodCat);
  const data = await api("/products?" + params);
  $("#prod-table").innerHTML = `<table class="table">
    <thead><tr><th>#</th><th>Produto</th><th>Tendência 14d</th><th>GMV est.</th>
    <th>Unidades</th><th>Preço</th><th>Cresc.</th><th>Criadores</th><th></th></tr></thead>
    <tbody>${data.products.map((p, i) => `
      <tr class="click" onclick="openProduct('${p.id}')">
        <td class="num" style="color:var(--faint)">${i + 1}</td>
        <td><b>${esc(p.name)}</b><br><small style="color:var(--muted)">${p.category} · ★ ${p.rating}</small></td>
        <td>${sparkline(p.curve)}</td>
        <td class="num">${fmtBRL(p.gmv)}</td>
        <td class="num">${fmtNum(p.units)}</td>
        <td class="num">${fmtBRL(p.price)}</td>
        <td>${p.growth >= 0 ? `<span class="pos">▲ ${p.growth}%</span>` : `<span class="neg">▼ ${Math.abs(p.growth)}%</span>`}</td>
        <td class="num">${p.creators_promoting}</td>
        <td><button class="btn small" onclick="event.stopPropagation();openProduct('${p.id}')">Detalhes</button></td>
      </tr>`).join("")}</tbody></table>`;
}

window.openProduct = async (id) => {
  openModal(`<div class="empty">Carregando análise…</div>`);
  const p = await api(`/products/${id}`);
  openModal(`
    <span class="badge gold">${p.category}</span>
    <h2 style="margin-top:8px">${esc(p.name)}</h2>
    <div class="grid cols-4" style="margin-top:14px">
      ${kpi("GMV est. 30d", fmtBRL(p.gmv), "receita estimada")}
      ${kpi("Unidades", fmtNum(p.units), "vendidas no período")}
      ${kpi("Ticket", fmtBRL(p.price), `comissão ~${p.commission}%`)}
      ${kpi("Crescimento", (p.growth >= 0 ? "+" : "") + p.growth + "%", p.growth >= 0 ? "em alta" : "em queda", p.growth >= 0 ? "var(--green)" : "var(--red)")}
    </div>
    <h3 style="margin-top:20px;font-size:14px">📈 Curva de vendas (14 dias)</h3>
    <div style="margin-top:6px">${areaChart(p.curve)}</div>
    <h3 style="margin-top:20px;font-size:14px">🎬 Vídeos que estão vendendo este produto</h3>
    <div class="vid-grid" style="margin-top:10px">${p.top_videos.map(videoCard).join("")}</div>
    <h3 style="margin-top:20px;font-size:14px">🔴 Lives com melhor GMV</h3>
    <table class="table" style="margin-top:6px"><tbody>${p.lives.map(l => `
      <tr><td><b>@${esc(l.host)}</b></td><td class="num">pico ${fmtNum(l.viewers_peak)}</td>
      <td class="num">${l.duration_min} min</td><td class="num pos">${fmtBRL(l.gmv)}</td>
      <td style="color:var(--muted)">${l.days_ago === 0 ? "hoje" : l.days_ago + "d atrás"}</td></tr>`).join("")}
    </tbody></table>
    <div style="margin-top:18px;display:flex;gap:10px">
      <button class="btn primary" onclick='createFor(${jattr(p.name)})'>✨ Criar conteúdo para este produto</button>
      <button class="btn" onclick='saveToLibrary("produto", ${jattr(p.id)}, ${jattr(p.name)}, ${jattr({ gmv: p.gmv, growth: p.growth })})'>📁 Salvar produto</button>
    </div>`);
};
window.createFor = (name) => {
  closeModal();
  location.hash = "#/studio";
  setTimeout(() => {
    switchStudioTab("hooks");
    const el = $("#hooks-product"); if (el) el.value = name;
  }, 120);
};

// ============================================================ CRIADORES
async function viewCriadores() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Criadores 👤</h1>
      <p>Encontre afiliados e criadores que já estão faturando no seu nicho — analise o que eles promovem e modele a estratégia.</p>
    </div></div>
    <div class="card">
      <div class="form-row">
        <div class="grow"><input id="cr-q" placeholder="Buscar por nome ou nicho…" /></div>
        <select id="cr-pf" style="width:170px">
          <option value="all">Todas as redes</option><option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option><option value="youtube">YouTube</option>
        </select>
        <button class="btn primary" onclick="loadCreators()">Buscar</button>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><div id="cr-table">…</div></div>`;
  loadCreators();
}
window.loadCreators = async () => {
  $("#cr-table").innerHTML = skeletonGrid(3, 60);
  const params = new URLSearchParams({ limit: "14" });
  const q = $("#cr-q")?.value.trim(); if (q) params.set("q", q);
  params.set("platform", $("#cr-pf")?.value || "all");
  const data = await api("/creators?" + params);
  $("#cr-table").innerHTML = `<table class="table">
    <thead><tr><th>Criador</th><th>Rede</th><th>Nicho</th><th>Seguidores</th>
    <th>Engaj.</th><th>Vídeos 30d</th><th>GMV est.</th><th>Top produto</th></tr></thead>
    <tbody>${data.creators.map(c => `
      <tr>
        <td><b>${esc(c.handle)}</b> ${c.verified ? '<span class="badge cyan">✓</span>' : ""}</td>
        <td style="color:${PF_META[c.platform].color};font-weight:700">${PF_META[c.platform].label}</td>
        <td><span class="badge gray">${c.niche}</span></td>
        <td class="num">${fmtNum(c.followers)}</td>
        <td class="num">${c.engagement_rate}%</td>
        <td class="num">${c.videos_30d}</td>
        <td class="num pos">${fmtBRL(c.gmv_est)}</td>
        <td style="color:var(--muted)">${esc(c.top_product)}</td>
      </tr>`).join("")}</tbody></table>`;
};

// ============================================================ LIVES
async function viewLives() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Vídeos & Lives 🔴</h1>
      <p>Live commerce em tempo real: quem está transmitindo, pico de audiência e GMV estimado por sessão.</p>
    </div><button class="btn" onclick="viewLives()">↻ Atualizar</button></div>
    <div id="live-kpis" class="grid cols-3"></div>
    <div class="grid cols-3" style="margin-top:14px" id="live-grid"></div>`;
  const data = await api("/lives?limit=12");
  $("#live-kpis").innerHTML =
    kpi("GMV total (painel)", fmtBRL(data.gmv_total), "soma das sessões listadas") +
    kpi("Ao vivo agora", data.ao_vivo_agora, "sessões transmitindo", "var(--red)") +
    kpi("Ticket médio", fmtBRL(data.gmv_total / Math.max(data.lives.length, 1)), "por sessão listada");
  $("#live-grid").innerHTML = data.lives.map(l => `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>@${esc(l.host)}</b>
        ${l.live_now ? '<span class="badge red pulse"><span class="dot"></span>AO VIVO</span>'
          : `<span class="badge gray">há ${Math.round(l.started_min_ago / 60)}h</span>`}
      </div>
      <div style="color:var(--muted);font-size:12.5px;margin-top:4px">
        ${PF_META[l.platform].label} · vendendo <b style="color:var(--text)">${esc(l.product)}</b></div>
      <div style="display:flex;gap:16px;margin-top:12px">
        <div><small style="color:var(--faint)">PICO</small><div class="num">${fmtNum(l.viewers_peak)}</div></div>
        <div><small style="color:var(--faint)">UNIDADES</small><div class="num">${fmtNum(l.units)}</div></div>
        <div><small style="color:var(--faint)">GMV EST.</small><div class="num pos">${fmtBRL(l.gmv)}</div></div>
      </div>
    </div>`).join("");
}

// ============================================================ NICHOS
async function viewNichos() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Radar de Nichos 🧭</h1>
      <p>Micro-nichos com poucos vídeos e muitas views — a janela de oportunidade antes da onda chegar.
      Ideal para canais dark e faceless.</p>
    </div></div>
    <div class="card"><div id="niche-table">…</div></div>`;
  const data = await api("/niches?limit=14");
  $("#niche-table").innerHTML = `<table class="table">
    <thead><tr><th>Nicho</th><th>Rede</th><th>Vídeos</th><th>Views totais</th>
    <th>Views/vídeo</th><th>Outlier</th><th>Status</th><th>Sinais</th></tr></thead>
    <tbody>${data.niches.map(n => `
      <tr>
        <td><b>${esc(n.niche)}</b><br><small style="color:var(--muted)">${n.sub_nicho} · ${esc(n.canal_exemplo)}</small></td>
        <td style="color:${PF_META[n.platform].color};font-weight:700">${PF_META[n.platform].label}</td>
        <td class="num">${n.videos}</td>
        <td class="num">${fmtNum(n.views_total)}</td>
        <td class="num">${fmtNum(n.views_por_video)}</td>
        <td style="min-width:120px"><div style="display:flex;align-items:center;gap:8px">
          <div style="flex:1;height:7px;background:var(--panel-2);border-radius:99px;overflow:hidden">
            <div style="width:${n.outlier_score}%;height:100%;background:linear-gradient(90deg,#8b7cf6,#f0b429)"></div>
          </div><b>${n.outlier_score}</b></div></td>
        <td><span class="badge ${n.status === "QUENTE" ? "red" : n.status === "EMERGENTE" ? "violet" : "gray"}">${n.status}</span></td>
        <td style="font-size:12px;color:var(--muted)">${n.monetizado ? "💰 monetizado · " : ""}${n.faceless ? "🎭 faceless · " : ""}${n.concorrentes} concorrentes</td>
      </tr>`).join("")}</tbody></table>`;
}

// ============================================================ ESTÚDIO IA
const STUDIO_TABS = [
  ["hooks", "🪝 Hooks virais"], ["script", "🎬 Roteiro UGC"], ["caption", "✍️ Legendas"],
  ["titles", "🎯 Títulos SEO"], ["lab", "🧪 Viral Lab"], ["voice", "🎙️ Voice Studio"],
];
async function viewStudio() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Estúdio IA ✨</h1>
      <p>Ecossistema de criação completo: hooks, roteiros, legendas, títulos, análise de vídeos virais
      e preparação de narração. Motor interno gratuito; conecte Groq/Gemini na aba de APIs para IA generativa real.</p>
    </div></div>
    <div class="tabs" id="studio-tabs">${STUDIO_TABS.map(([id, lb], i) =>
      `<button data-tab="${id}" class="${i === 0 ? "active" : ""}">${lb}</button>`).join("")}</div>
    <div id="studio-content"></div>`;
  $$("#studio-tabs button").forEach(b => b.onclick = () => switchStudioTab(b.dataset.tab));
  switchStudioTab("hooks");
}
window.switchStudioTab = (tab) => {
  $$("#studio-tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  ({ hooks: tabHooks, script: tabScript, caption: tabCaption,
     titles: tabTitles, lab: tabLab, voice: tabVoice })[tab]();
};

function tabHooks() {
  $("#studio-content").innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>Gerador de hooks</h3>
        <div class="field" style="margin-bottom:10px"><label>Produto / tema</label>
          <input id="hooks-product" placeholder="ex: mini processador de alimentos" /></div>
        <div class="field" style="margin-bottom:10px"><label>Nicho (opcional)</label>
          <select id="hooks-niche"><option value="">geral</option>
          ${["beleza","casa","tech","fitness","moda","pets","maternidade","automotivo"]
            .map(n => `<option>${n}</option>`).join("")}</select></div>
        <div class="field" style="margin-bottom:14px"><label>Tom</label>
          <select id="hooks-tone"><option>direto</option><option>divertido</option>
          <option>urgente</option><option>educativo</option></select></div>
        <button class="btn primary" id="hooks-go">⚡ Gerar 10 hooks</button>
      </div>
      <div class="card"><h3>Resultado <span id="hooks-engine"></span></h3><div id="hooks-out" class="out-block">Preencha o produto e gere seus hooks.</div></div>
    </div>`;
  $("#hooks-go").onclick = async () => {
    const product = $("#hooks-product").value.trim();
    if (!product) return toast("Informe o produto", true);
    $("#hooks-out").textContent = "Gerando…";
    const data = await api("/ai/hooks", { method: "POST", body: {
      product, niche: $("#hooks-niche").value, tone: $("#hooks-tone").value, count: 10 } });
    $("#hooks-engine").innerHTML = `<span class="badge ${data.engine === "llm" ? "green" : "violet"}">${data.engine}</span>`;
    $("#hooks-out").innerHTML = data.hooks.map((h, i) => `
      <div class="hook-item"><span class="n">${String(i + 1).padStart(2, "0")}</span>
        <div><div>${esc(h.hook)}</div>
        <small style="color:var(--faint)">${esc(h.formula)} ·
        <span class="link-gold" onclick="copyText(${JSON.stringify(h.hook)})">copiar</span></small></div>
      </div>`).join("");
  };
}

function tabScript() {
  $("#studio-content").innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>Roteiro de vídeo curto</h3>
        <div class="field" style="margin-bottom:10px"><label>Produto / tema</label>
          <input id="script-product" placeholder="ex: escova removedora de pelos" /></div>
        <div class="form-row" style="margin-bottom:10px">
          <div class="field grow"><label>Duração (s)</label><input id="script-dur" type="number" value="30" min="10" max="180" /></div>
          <div class="field grow"><label>Formato</label>
            <select id="script-fmt"><option value="ugc">UGC (testemunhal)</option>
            <option value="dark">Dark / faceless</option><option value="lista">Lista / top 3</option></select></div>
        </div>
        <button class="btn primary" id="script-go">🎬 Gerar roteiro completo</button>
      </div>
      <div class="card"><h3>Roteiro <span id="script-engine"></span></h3><div id="script-out" class="out-block">O roteiro cena a cena aparece aqui.</div></div>
    </div>`;
  $("#script-go").onclick = async () => {
    const product = $("#script-product").value.trim();
    if (!product) return toast("Informe o produto", true);
    $("#script-out").textContent = "Montando roteiro…";
    const s = await api("/ai/script", { method: "POST", body: {
      product, duration: +$("#script-dur").value, format: $("#script-fmt").value } });
    $("#script-engine").innerHTML = `<span class="badge ${s.engine === "llm" ? "green" : "violet"}">${s.engine}</span>`;
    $("#script-out").innerHTML = `
      <b>🎯 Título:</b> ${esc(s.titulo_sugerido)}<br>
      <b>🪝 Hook (0-2s):</b> “${esc(s.hook)}”<br>
      <b>🎵 Música:</b> ${esc(s.musica)} · <b>⏱ ${s.duracao}s</b>
      <div class="divider"></div>
      ${s.cenas.map(c => `<div class="scene">
        <div class="scene-head"><span class="badge gold">${esc(c.nome)}</span><b>${esc(c.tempo)}</b>
        <small style="color:var(--faint)">edição: ${esc(c.edicao)}</small></div>
        <div style="font-size:13px;color:var(--muted)">${esc(c.descricao)}</div></div>`).join("")}
      <div class="divider"></div>
      <b>🎙️ Narração sugerida:</b><br>“${esc(s.narracao)}”
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn small" onclick="copyText(${JSON.stringify(s.narracao)}, 'Narração copiada!')">📋 Copiar narração</button>
        <button class="btn small" onclick='sendToVoice(${JSON.stringify(s.narracao)})'>🎙️ Enviar pro Voice Studio</button>
      </div>
      <div class="divider"></div><b>⚡ Retenção:</b><br>${s.dicas_retencao.map(d => "• " + esc(d)).join("<br>")}`;
  };
}
window.sendToVoice = (text) => {
  switchStudioTab("voice");
  setTimeout(() => { $("#voice-text").value = text; }, 80);
};

function tabCaption() {
  $("#studio-content").innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>Legenda + hashtags</h3>
        <div class="field" style="margin-bottom:10px"><label>Produto / tema</label>
          <input id="cap-product" placeholder="ex: luminária LED de mesa" /></div>
        <div class="field" style="margin-bottom:10px"><label>Rede social</label>
          <select id="cap-pf"><option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option><option value="youtube">YouTube</option></select></div>
        <div class="field" style="margin-bottom:14px"><label>Benefício principal (opcional)</label>
          <input id="cap-benefit" placeholder="ex: economiza 80% de energia" /></div>
        <button class="btn primary" id="cap-go">✍️ Gerar legenda</button>
      </div>
      <div class="card"><h3>Resultado</h3><div id="cap-out" class="out-block">A legenda pronta para colar aparece aqui.</div></div>
    </div>`;
  $("#cap-go").onclick = async () => {
    const product = $("#cap-product").value.trim();
    if (!product) return toast("Informe o produto", true);
    $("#cap-out").textContent = "Escrevendo…";
    const c = await api("/ai/caption", { method: "POST", body: {
      product, platform: $("#cap-pf").value, benefit: $("#cap-benefit").value } });
    const full = c.caption + "\n\n" + c.hashtags.join(" ");
    $("#cap-out").innerHTML = `${esc(c.caption)}<div class="divider"></div>
      <div class="tags-row">${c.hashtags.map(t => `<span class="mini-tag">${esc(t)}</span>`).join("")}</div>
      <div style="margin-top:12px"><button class="btn small" onclick="copyText(${JSON.stringify(full)})">📋 Copiar tudo</button></div>`;
  };
}

function tabTitles() {
  $("#studio-content").innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>Títulos + SEO YouTube</h3>
        <div class="field" style="margin-bottom:14px"><label>Tema do vídeo</label>
          <input id="tt-theme" placeholder="ex: garrafa térmica que mantém gelo 24h" /></div>
        <button class="btn primary" id="tt-go">🎯 Gerar 10 títulos + descrição + tags</button>
      </div>
      <div class="card"><h3>Pacote SEO</h3><div id="tt-out" class="out-block">Títulos clicáveis, descrição com capítulos e tags aparecem aqui.</div></div>
    </div>`;
  $("#tt-go").onclick = async () => {
    const theme = $("#tt-theme").value.trim();
    if (!theme) return toast("Informe o tema", true);
    $("#tt-out").textContent = "Otimizando SEO…";
    const t = await api("/ai/titles", { method: "POST", body: { theme } });
    $("#tt-out").innerHTML = `<b>Títulos:</b><br>${t.titles.map((x, i) => `
      <div class="hook-item"><span class="n">${i + 1}.</span><div>${esc(x)}
      <span class="link-gold" onclick="copyText(${JSON.stringify(x)})">copiar</span></div></div>`).join("")}
      <div class="divider"></div><b>Descrição:</b><br>${esc(t.description).replace(/\n/g, "<br>")}
      <div style="margin-top:8px"><button class="btn small" onclick="copyText(${JSON.stringify(t.description)})">📋 Copiar descrição</button></div>
      <div class="divider"></div><b>Tags:</b><br>
      <div class="tags-row" style="margin-top:6px">${t.tags.map(x => `<span class="mini-tag">${esc(x)}</span>`).join("")}</div>
      <div style="margin-top:8px"><button class="btn small" onclick="copyText(${JSON.stringify(t.tags.join(", "))})">📋 Copiar tags</button></div>`;
  };
}

function tabLab() {
  $("#studio-content").innerHTML = `
    <div class="card">
      <h3>Viral Lab — engenharia reversa de vídeo viral</h3>
      <div class="form-row">
        <div class="grow"><input id="lab-subject" placeholder="Cole o link ou descreva o vídeo/canal para analisar…" /></div>
        <button class="btn primary" id="lab-go">🧪 Analisar</button>
      </div>
    </div>
    <div id="lab-out" style="margin-top:14px"></div>`;
  $("#lab-go").onclick = async () => {
    const subject = $("#lab-subject").value.trim();
    if (!subject) return toast("Cole um link ou descrição", true);
    $("#lab-out").innerHTML = skeletonGrid(2, 90);
    const a = await api("/ai/analyze", { method: "POST", body: { subject } });
    $("#lab-out").innerHTML = `
      <div class="grid cols-2">
        <div class="card">
          <h3>Diagnóstico <span class="badge ${a.engine === "llm" ? "green" : "violet"}">${a.engine}</span></h3>
          <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">
            ${scoreRing(a.outlier_score, 64)}
            <div><b style="font-size:15px">Outlier score ${a.outlier_score}</b><br>
            <small style="color:var(--muted)">${esc(a.veredito)}</small></div>
          </div>
          <b>Formato:</b> ${esc(a.formato_detectado)}<br><br>
          <b>Hook detectado:</b> ${esc(a.hook_detectado)}
          <div class="divider"></div><b>Beats do vídeo:</b><br>
          ${a.beats.map(b => `<div class="scene"><div class="scene-head"><span class="badge gold">${b.tempo}</span></div>
            <div style="font-size:13px;color:var(--muted)">${esc(b.funcao)}</div></div>`).join("")}
        </div>
        <div class="card">
          <h3>Por que viralizou (hipóteses)</h3>
          ${a.hipoteses_virais.map(h => `<div class="hook-item"><span class="n">→</span><div>${esc(h)}</div></div>`).join("")}
          <div class="divider"></div><h3 style="margin-bottom:8px">Plano de replicação</h3>
          ${a.plano_replicacao.map((p, i) => `<div class="hook-item"><span class="n">${i + 1}.</span><div>${esc(p)}</div></div>`).join("")}
          <div style="margin-top:10px">
            <button class="btn primary" onclick='createFor(${jattr(subject)})'>✨ Criar conteúdo a partir daqui</button>
          </div>
        </div>
      </div>`;
  };
}

function tabVoice() {
  $("#studio-content").innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>Voice Studio — preparação de narração</h3>
        <div class="field" style="margin-bottom:10px"><label>Roteiro / texto</label>
          <textarea id="voice-text" rows="7" placeholder="Cole aqui o roteiro ou a narração do seu vídeo dark…"></textarea></div>
        <div class="form-row" style="margin-bottom:12px">
          <div class="field grow"><label>Tom</label>
            <select id="voice-tone"><option value="suspense">Suspense (pausas longas)</option>
            <option value="energetico">Energético (ritmo rápido)</option>
            <option value="documental">Documental</option><option value="jornalistico">Jornalístico</option></select></div>
          <button class="btn primary" id="voice-go">🎙️ Preparar marcação</button>
        </div>
        <div class="form-row">
          <button class="btn" id="voice-play">▶ Ouvir prévia (voz do navegador · grátis)</button>
          <button class="btn" id="voice-stop">■ Parar</button>
          <select id="voice-rate" style="width:130px"><option value="0.85">Lento</option>
          <option value="1" selected>Normal</option><option value="1.15">Rápido</option></select>
        </div>
      </div>
      <div class="card"><h3>Marcação de pausas & emoção</h3>
        <div id="voice-out" class="out-block">A versão marcada com pausas dramáticas aparece aqui — pronta para colar em qualquer TTS.</div>
      </div>
    </div>`;
  $("#voice-go").onclick = async () => {
    const text = $("#voice-text").value.trim();
    if (text.length < 4) return toast("Cole um texto primeiro", true);
    const n = await api("/ai/narration", { method: "POST", body: { text, tone: $("#voice-tone").value } });
    $("#voice-out").innerHTML = `${esc(n.marcacao)}<div class="divider"></div>
      <small style="color:var(--muted)">Duração estimada: <b>${n.duracao_estimada_s}s</b> · ${esc(n.dica)}</small>
      <div style="margin-top:10px"><button class="btn small" onclick="copyText(${JSON.stringify(n.marcacao)})">📋 Copiar marcação</button></div>`;
    $("#voice-play").dataset.text = n.para_leitura;
  };
  $("#voice-play").onclick = () => {
    const txt = $("#voice-play").dataset.text || $("#voice-text").value;
    if (!txt.trim()) return toast("Prepare ou cole um texto primeiro", true);
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(txt);
    u.lang = "pt-BR"; u.rate = +$("#voice-rate").value; u.pitch = 0.92;
    const br = speechSynthesis.getVoices().find(v => v.lang.startsWith("pt"));
    if (br) u.voice = br;
    speechSynthesis.speak(u);
    toast("Reproduzindo prévia…");
  };
  $("#voice-stop").onclick = () => speechSynthesis.cancel();
}

// ============================================================ BIBLIOTECA
async function viewBiblioteca() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Biblioteca 📁</h1>
      <p>Tudo o que você garimpou: vídeos, produtos, criadores e roteiros salvos para revisitar.</p>
    </div></div>
    <div class="card"><div id="lib-list">…</div></div>`;
  const data = await api("/library");
  if (!data.items.length) {
    $("#lib-list").innerHTML = `<div class="empty">Biblioteca vazia — salve itens no Radar Viral, Produtos ou Estúdio IA.</div>`;
    return;
  }
  const icon = { video: "🎬", produto: "📦", criador: "👤", roteiro: "✨" };
  $("#lib-list").innerHTML = `<table class="table">
    <thead><tr><th></th><th>Título</th><th>Tipo</th><th>Salvo em</th><th></th></tr></thead>
    <tbody>${data.items.map(i => `
      <tr>
        <td style="font-size:18px">${icon[i.kind] || "📌"}</td>
        <td><b>${esc(i.title || "(sem título)")}</b><br>
          <small style="color:var(--faint)">${esc(i.ref || "")}</small></td>
        <td><span class="badge gray">${i.kind}</span></td>
        <td style="color:var(--muted)">${i.saved_at?.slice(0, 10)}</td>
        <td><button class="btn small danger" onclick="removeLib('${i.id}')">Remover</button></td>
      </tr>`).join("")}</tbody></table>`;
}
window.removeLib = async (id) => {
  await api(`/library/${id}`, { method: "DELETE" });
  toast("Item removido"); viewBiblioteca();
};

// ============================================================ APIS & CONEXÕES
async function viewApis() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>APIs & Conexões 🔌</h1>
      <p>Arquitetura plugável: sem chaves, a plataforma roda em modo demonstração.
      Conecte as APIs oficiais (todas gratuitas) para operar com dados reais.</p>
    </div></div>
    <div id="api-cards" class="grid cols-2"></div>
    <div class="section-title">💡 Outras opções de APIs que se encaixam (pesquisadas)</div>
    <div class="card" id="alt-apis"></div>`;

  const st = await api("/status");
  const cfg = await api("/settings");
  const defs = [
    { k: "youtube", icon: "▶", fields: [["YOUTUBE_API_KEY", "Chave da YouTube Data API v3", "password"]],
      docs: "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
      how: "Google Cloud → crie um projeto → ative 'YouTube Data API v3' → Credenciais → Criar chave de API. Custo zero: 10.000 unidades/dia (1 busca = 100 unidades)." },
    { k: "tiktok", icon: "♪", fields: [["TIKTOK_CLIENT_KEY", "Client Key (Research API)", "password"],
      ["TIKTOK_CLIENT_SECRET", "Client Secret", "password"]],
      docs: "https://developers.tiktok.com/products/research-api/",
      how: "Oficial e gratuita, porém restrita: exige vínculo acadêmico/institucional e aprovação manual (pode levar semanas). Sem aprovação, o modo demo cobre o TikTok." },
    { k: "instagram", icon: "◎", fields: [["IG_ACCESS_TOKEN", "Access token de longa duração", "password"],
      ["IG_USER_ID", "ID da conta Instagram profissional", "text"]],
      docs: "https://developers.facebook.com/docs/instagram-api",
      how: "Meta for Developers → crie um app Business → adicione o produto Instagram → vincule uma conta Business/Creator a uma Página → gere token de longa duração. Busca por hashtag: limite oficial de 30 hashtags únicas a cada 7 dias." },
    { k: "ia", icon: "✨", fields: [["GROQ_API_KEY", "Groq API key (opcional)", "password"],
      ["GEMINI_API_KEY", "Gemini API key (opcional)", "password"]],
      docs: "https://console.groq.com/keys",
      how: "O motor interno de copywriting já é 100% gratuito. Groq (Llama) e Google Gemini possuem tiers gratuitos generosos para elevar a qualidade dos textos gerados." },
  ];

  $("#api-cards").innerHTML = defs.map(d => {
    const s = st.providers[d.k];
    return `<div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0"><span style="font-size:18px">${d.icon}</span> ${s.oficial}</h3>
        <span class="badge ${s.conectado ? "green" : "gray"}">${s.conectado ? "● conectado" : "○ não conectado"}</span>
      </div>
      <small style="color:var(--muted)">${s.custo}</small>
      <div style="margin-top:12px">${d.fields.map(([name, label, type]) => `
        <div class="field" style="margin-bottom:8px"><label>${label}</label>
        <input type="${type}" id="set-${name}" placeholder="${cfg.settings[name] ? "••• " + cfg.settings[name] + " (salvo)" : "colar aqui…"}" /></div>`).join("")}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn primary small" onclick="saveProvider('${d.k}', ${JSON.stringify(d.fields.map(f => f[0]))})">💾 Salvar</button>
        <button class="btn small" onclick="testProvider('${d.k}')">🔍 Testar conexão</button>
        <a class="btn small ghost" href="${d.docs}" target="_blank" rel="noopener">📖 Como obter</a>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--faint);line-height:1.55">${d.how}</div>
      <div id="test-${d.k}" style="margin-top:8px"></div>
    </div>`;
  }).join("");

  const alts = [
    ["Apify (atores TikTok/IG)", "Scrapers prontos com créditos grátis iniciais — alternativa rápida enquanto a Research API não sai.", "https://apify.com"],
    ["RapidAPI (marketplace)", "Dezenas de APIs de dados sociais com tier gratuito (busca TikTok, métricas IG, trends).", "https://rapidapi.com"],
    ["Google Trends / pytrends", "Termos em alta por região e período — ótimo termômetro gratuito para o Radar.", "https://trends.google.com"],
    ["Reddit API (grátis)", "Descoberta de micro-nichos e dor do público por subreddit.", "https://www.reddit.com/dev/api"],
    ["Groq (Llama) — grátis", "LLM ultra-rápido com tier gratuito: usado pelo Estúdio IA quando conectado.", "https://console.groq.com"],
    ["Google Gemini — grátis", "Tier gratuito generoso para geração de texto no Estúdio IA.", "https://aistudio.google.com/apikey"],
    ["YouTube Data API v3", "Oficial e gratuita — única com busca pública real entre as três redes.", "https://developers.google.com/youtube/v3"],
    ["Web Speech API", "Síntese de voz gratuita no navegador usada no Voice Studio (prévia de narração).", "https://developer.mozilla.org/docs/Web/API/Web_Speech_API"],
  ];
  $("#alt-apis").innerHTML = `<table class="table">
    <thead><tr><th>Opção</th><th>Por que se encaixa</th><th></th></tr></thead>
    <tbody>${alts.map(([n, d, u]) => `
      <tr><td><b>${n}</b></td><td style="color:var(--muted)">${d}</td>
      <td><a class="link-gold" href="${u}" target="_blank" rel="noopener">visitar ↗</a></td></tr>`).join("")}
    </tbody></table>`;
}
window.saveProvider = async (kind, fields) => {
  const patch = {};
  fields.forEach(f => { const v = $(`#set-${f}`)?.value?.trim(); if (v) patch[f] = v; });
  if (!Object.keys(patch).length) return toast("Preencha ao menos um campo", true);
  await api("/settings", { method: "POST", body: { settings: patch } });
  toast("Credenciais salvas ✔");
  loadStatus(); viewApis();
};
window.testProvider = async (kind) => {
  $(`#test-${kind}`).innerHTML = `<span class="badge gray">testando…</span>`;
  const r = await api(`/settings/test/${kind}`, { method: "POST" });
  $(`#test-${kind}`).innerHTML =
    `<span class="badge ${r.ok ? "green" : "red"}">${esc(r.message)}</span>`;
};

// ------------------------------------------------------------------ boot
window.saveToLibrary = saveToLibrary;
window.copyText = copyText;
window.openProduct = window.openProduct;
window.addEventListener("hashchange", router);
loadStatus().then(router);
