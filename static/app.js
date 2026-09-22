/* ============================================================
   MineraAI — SPA (JS puro, sem build)
   Módulos: Dashboard · Radar Viral · Curadoria · Produtos · Criadores ·
            Lives · Nichos · Estúdio IA · Biblioteca · APIs
   ============================================================ */

// ------------------------------------------------------------------ utils
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
const state = { status: null, lastSearch: null, curadoria: { selected: new Set(), filter: {} } };

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
        <span class="src-badge src-${v.source}">${{ oficial: "oficial", coleta: "coleta real", n8n: "n8n automação", demo: "demo" }[v.source] || v.source}</span></div>
      <div class="vid-metrics">
        <span>👁 <b>${fmtNum(v.views)}</b></span>
        <span>❤ <b>${fmtNum(v.likes)}</b></span>
        <span>💬 <b>${fmtNum(v.comments)}</b></span>
        <span>⚡ <b>${v.engagement}%</b></span>
      </div>
      ${v.hashtags?.length ? `<div class="tags-row">${v.hashtags.slice(0, 4)
        .map(t => `<span class="mini-tag">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="vid-actions">
        <button class="btn small primary" onclick='sendToCuradoria(${jattr(v)}, ${jattr(v.title)})'>✅ Curar</button>
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

async function sendToCuradoria(video, query) {
  try {
    const res = await api("/curation/items", { method: "POST", body: { videos: [video], query: query || video.title, source: "manual" } });
    toast(`Enviado para curadoria ✅ (${res.criados} novo${res.criados!==1?'s':''})`);
  } catch (e) { toast(e.message, true); }
}
window.sendToCuradoria = sendToCuradoria;

// ============================================================ ROTAS
const routes = {
  dashboard: viewDashboard,
  radar: viewRadar,
  curadoria: viewCuradoria,
  produtos: viewProdutos,
  criadores: viewCriadores,
  lives: viewLives,
  nichos: viewNichos,
  studio: viewStudio,
  fabrica: viewFabrica,
  biblioteca: viewBiblioteca,
  apis: viewApis,
};

let fabricaTimer = null;

function router() {
  if (fabricaTimer) { clearTimeout(fabricaTimer); fabricaTimer = null; }
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
      <p>O garimpo do dia: produtos quentes, lives faturando, curadoria e nichos emergentes — tudo em um só painel.</p>
    </div></div>
    <div class="grid cols-4" id="kpis"></div>
    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>✅ Curadoria — fila</h3><div id="dash-cura">…</div></div>
      <div class="card"><h3>🔴 Lives faturando agora</h3><div id="dash-lives">…</div></div>
    </div>
    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>📦 Top produtos (GMV est. 30d)</h3><div id="dash-products">…</div></div>
      <div class="card"><h3>🧭 Nichos com maior outlier score</h3><div id="dash-niches">…</div></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>📈 Termos em alta agora — Google Trends BR <span id="trends-fonte" class="badge gray"></span></h3><div id="dash-trends">…</div></div>`;

  const [prod, lives, niches, trends, cura] = await Promise.all([
    api("/products?limit=6&sort=gmv"), api("/lives?limit=5"), api("/niches?limit=5"),
    api("/trends?limit=12").catch(() => ({ terms: [], fonte: "indisponível" })),
    api("/curation/stats").catch(() => ({ total: 0, por_status: {}, outliers_75: 0, novos_24h: 0 })),
  ]);

  $("#trends-fonte").textContent = trends.fonte || "";
  $("#dash-trends").innerHTML = trends.terms?.length
    ? `<div class="tags-row" style="gap:8px">${trends.terms.map(t => `
        <span class="chip" style="cursor:pointer" onclick="trendToRadar(${jattr(t.term)})">
          🔥 ${esc(t.term)} <small class="num" style="color:var(--gold)">${fmtNum(t.traffic)}+</small>
        </span>`).join("")}</div>
      <small style="color:var(--faint);display:block;margin-top:10px">Clique em um termo para garimpá-lo no Radar Viral.</small>`
    : `<div class="empty">Google Trends indisponível neste ambiente (rede restrita). Em produção, este widget mostra os termos mais buscados do Brasil em tempo real.</div>`;

  const avgGrowth = prod.products.reduce((s, p) => s + p.growth, 0) / Math.max(prod.products.length, 1);
  $("#kpis").innerHTML = `
    ${kpi("GMV total garimpado", fmtBRL(prod.total_gmv), "soma dos top produtos · 30 dias")}
    ${kpi("Curadoria fila", `${cura.total || 0} itens`, `${cura.novos_24h || 0} novos 24h · ${cura.outliers_75 || 0} outliers`, "var(--cyan)")}
    ${kpi("Lives ativas", lives.ao_vivo_agora, `${fmtBRL(lives.gmv_total)} em GMV no painel`, "var(--red)")}
    ${kpi("Nicho mais quente", niches.niches[0]?.outlier_score + " pts", niches.niches[0]?.niche || "", "var(--violet)")}`;

  $("#dash-cura").innerHTML = `
    <div class="grid cols-3" style="margin-bottom:12px">
      ${Object.entries(cura.por_status || {}).map(([s, n]) => `<div class="card kpi" style="padding:12px"><span class="label">${s}</span><span class="value">${n}</span></div>`).join("")}
    </div>
    <div style="display:flex;gap:8px"><button class="btn small primary" onclick="location.hash='#/curadoria'">✅ Abrir curadoria</button>
    <button class="btn small" onclick="location.hash='#/radar'">🔎 Radar</button></div>`;

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

window.trendToRadar = (term) => {
  state.lastSearch = { q: term };
  location.hash = "#/radar";
  setTimeout(() => { const el = $("#radar-q"); if (el) { el.value = term; runRadar(); } }, 150);
};

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
        <button class="btn" id="radar-cura-all">✅ Curar todos</button>
      </div>
    </div>
    <div id="radar-summary" style="margin-top:14px"></div>
    <div style="display:grid;grid-template-columns:1fr 300px;gap:14px;margin-top:14px" class="radar-layout">
      <div id="radar-results">${skeletonGrid(6)}</div>
      <div>
        <div class="card"><h3># Hashtags dominantes</h3><div id="radar-tags">…</div></div>
        <div class="card" style="margin-top:14px"><h3>🎵 Sons em alta</h3><div id="radar-sounds">…</div></div>
        <div class="card" style="margin-top:14px"><h3>👤 Criadores no tema</h3><div id="radar-creators">…</div></div>
        <div class="card" style="margin-top:14px"><h3>💡 Ideias de pauta <span class="badge gray">Reddit + Google</span></h3><div id="radar-ideas">…</div></div>
      </div>
    </div>`;
  $("#radar-go").onclick = runRadar;
  $("#radar-cura-all").onclick = async () => {
    if (!window._lastRadarVideos?.length) return toast("Garimpe primeiro", true);
    try {
      const res = await api("/curation/items", { method: "POST", body: { videos: window._lastRadarVideos, query: $("#radar-q").value, source: "radar" } });
      toast(`✅ ${res.criados} vídeos enviados para curadoria!`);
    } catch (e) { toast(e.message, true); }
  };
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
  window._lastRadarVideos = data.videos;
  const { source_breakdown: sb } = data;
  const real = sb.oficial + sb.coleta;
  $("#radar-summary").innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <span class="badge gold">${data.total} vídeos encontrados</span>
      <span class="badge green">oficial: ${sb.oficial}</span>
      <span class="badge cyan">coleta real: ${sb.coleta}</span>
      ${sb.n8n ? `<span class="badge gold">n8n: ${sb.n8n}</span>` : ""}
      <span class="badge violet">demo: ${sb.demo}</span>
      ${(data.coleta_errors || []).length ? `<span class="badge gray" title="${esc(data.coleta_errors.join(" · "))}">⚠ coleta parcial</span>` : ""}
      ${real === 0 ? '<small style="color:var(--muted)">— conecte chaves em <span class="link-gold" onclick="location.hash=&quot;#/apis&quot;">APIs & Conexões</span> ou verifique a coleta Scrapling</small>' : ""}
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

  api("/api/ideas?q=" + encodeURIComponent(q)).then(ideas => {
    const sug = (ideas.sugestoes || []).map(s => `
      <span class="chip" style="margin:3px;cursor:pointer;font-size:11.5px"
        onclick="radarUseIdea(${jattr(s)})">${esc(s)}</span>`).join("");
    const red = (ideas.reddit || []).slice(0, 4).map(r => `
      <div style="padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:12px">
        <a href="${esc(r.url)}" target="_blank" rel="noopener" style="font-weight:600;line-height:1.35;display:block">${esc(r.title)}</a>
        <small style="color:var(--muted)">▲ ${fmtNum(r.score)} · 💬 ${fmtNum(r.comments)} · r/${esc(r.subreddit)}</small>
      </div>`).join("");
    $("#radar-ideas").innerHTML = (sug || red)
      ? (sug ? `<div class="tags-row" style="margin-bottom:8px">${sug}</div>` : "") +
        (red || "")
      : `<small style="color:var(--faint)">Indisponível neste ambiente (sem rede externa). Em produção mostra o top do Reddit + autocomplete do Google para o tema.</small>`;
  }).catch(() => {});
}
window.radarUseIdea = (term) => { $("#radar-q").value = term; runRadar(); };

// ============================================================ CURADORIA ✅
const CURA_STATUS = {
  novo: { label: "Novo", color: "gray", icon: "🆕" },
  em_analise: { label: "Em análise", color: "cyan", icon: "🔍" },
  aprovado: { label: "Aprovado", color: "green", icon: "✅" },
  rejeitado: { label: "Rejeitado", color: "red", icon: "❌" },
  arquivado: { label: "Arquivado", color: "gray", icon: "📦" },
  publicado: { label: "Publicado", color: "violet", icon: "🚀" },
};

async function viewCuradoria() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Curadoria ✅</h1>
      <p>Pipeline completo: coleta → filtragem automática (regras + blacklist) → enriquecimento IA → decisão humana → biblioteca/fábrica. 
      Use filtros, aprove em lote e deixe o n8n automatizar o resto.</p>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn small" onclick="viewCuradoria()">↻ Atualizar</button>
      <button class="btn small primary" onclick="openCuraRules()">⚙️ Regras</button>
      <button class="btn small" onclick="location.hash='#/radar'">🔎 Radar</button>
    </div>
    </div>

    <div class="grid cols-4" id="cura-kpis" style="margin-bottom:14px"></div>

    <div class="card">
      <div class="form-row">
        <div class="grow"><input id="cura-q" placeholder="Buscar por título, autor, tag ou query de origem…" /></div>
        <select id="cura-status" style="width:160px">
          <option value="">Todos os status</option>
          ${Object.keys(CURA_STATUS).map(s => `<option value="${s}">${CURA_STATUS[s].icon} ${CURA_STATUS[s].label}</option>`).join("")}
        </select>
        <select id="cura-pf" style="width:140px">
          <option value="all">Todas redes</option><option value="tiktok">TikTok</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option>
        </select>
        <select id="cura-minscore" style="width:130px">
          <option value="0">Score: todos</option><option value="50">≥50</option><option value="70">≥70</option><option value="75">≥75 outlier</option><option value="85">≥85 top</option>
        </select>
        <select id="cura-sort" style="width:130px">
          <option value="score">Maior score</option><option value="recent">Mais recentes</option><option value="oldest">Mais antigos</option><option value="views">Mais views</option>
        </select>
        <button class="btn primary" id="cura-go">Filtrar</button>
      </div>

      <div class="form-row" style="margin-top:12px">
        <div class="grow"><input id="cura-auto-q" placeholder="Auto-curar: digite keyword e clique em garimpar → curadoria (ex: garrafa térmica)" /></div>
        <button class="btn primary" id="cura-auto-go">⚡ Garimpar e curar</button>
        <button class="btn" id="cura-outliers-go">🔥 Só outliers ≥75</button>
      </div>

      <div id="cura-bulk" style="margin-top:12px;display:none" class="card" style="background:var(--panel-2)">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <span class="badge gold"><span id="cura-sel-count">0</span> selecionados</span>
          <button class="btn small primary" onclick="curaBulk('aprovado')">✅ Aprovar</button>
          <button class="btn small" onclick="curaBulk('em_analise')">🔍 Em análise</button>
          <button class="btn small" onclick="curaBulk('rejeitado')">❌ Rejeitar</button>
          <button class="btn small" onclick="curaBulk('arquivado')">📦 Arquivar</button>
          <button class="btn small ghost" onclick="curaClearSel()">Limpar seleção</button>
        </div>
      </div>
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>📋 Fila de curadoria <span id="cura-total" class="badge gray"></span></h3><div id="cura-list">…</div></div>
      <div>
        <div class="card"><h3>🔥 Outliers agora <span class="badge gold">≥75</span></h3><div id="cura-outliers">…</div></div>
        <div class="card" style="margin-top:14px"><h3>⚙️ Regras ativas</h3><div id="cura-rules-mini">…</div></div>
        <div class="card" style="margin-top:14px"><h3>🧭 Como funciona</h3>
          <div style="font-size:12.5px;line-height:1.7;color:var(--muted)">
            <b style="color:var(--text)">1. Coleta</b> — Radar, Mineração n8n, Ingestão ou manual<br>
            <b style="color:var(--text)">2. Filtragem</b> — blacklist, min views/score/engajamento, idade, plataforma<br>
            <b style="color:var(--text)">3. Enriquecimento</b> — IA gera hooks, análise Viral Lab, tags, título<br>
            <b style="color:var(--text)">4. Decisão</b> — kanban humano (aprovar/rejeitar) ou auto-aprovação por score<br>
            <b style="color:var(--text)">5. Ação</b> — aprovados vão pra Biblioteca + podem virar vídeo na Fábrica ou webhook externo<br><br>
            <span class="badge cyan">Dica</span> No n8n: <code>n8n/curadoria-*.json</code> já automatiza tudo.
          </div>
        </div>
      </div>
    </div>`;

  $("#cura-go").onclick = loadCuradoria;
  $("#cura-q").addEventListener("keydown", e => { if (e.key === "Enter") loadCuradoria(); });
  $("#cura-auto-go").onclick = async () => {
    const q = $("#cura-auto-q").value.trim();
    if (!q) return toast("Digite uma keyword", true);
    $("#cura-auto-go").textContent = "Garimpando…";
    try {
      const r = await api("/curation/auto-curate", { method: "POST", body: { query: q, platform: "all", limit: 12 } });
      toast(`✅ ${r.criados} novos na curadoria para "${q}"`);
      loadCuradoria();
    } catch (e) { toast(e.message, true); }
    $("#cura-auto-go").textContent = "⚡ Garimpar e curar";
  };
  $("#cura-outliers-go").onclick = () => {
    $("#cura-status").value = "";
    $("#cura-minscore").value = "75";
    $("#cura-sort").value = "score";
    loadCuradoria();
  };

  loadCuradoria();
  loadCuradoriaOutliers();
  loadCuradoriaRulesMini();
}

async function loadCuradoria() {
  const params = new URLSearchParams({
    status: $("#cura-status").value,
    platform: $("#cura-pf").value,
    min_score: $("#cura-minscore").value,
    sort: $("#cura-sort").value,
    q: $("#cura-q").value.trim(),
    limit: "40",
  });
  $("#cura-list").innerHTML = skeletonGrid(4, 160);
  const data = await api("/curation/queue?" + params);
  state.curadoria.lastData = data.items;
  $("#cura-total").textContent = `${data.items.length} itens`;

  // kpis
  const s = data.stats;
  $("#cura-kpis").innerHTML = `
    ${kpi("Total fila", s.total || 0, `${s.novos_24h || 0} novos 24h`, "var(--gold)")}
    ${kpi("Outliers ≥75", s.outliers_75 || 0, "alta oportunidade", "var(--cyan)")}
    ${kpi("Aprovados", s.por_status?.aprovado || 0, `${s.por_status?.publicado || 0} publicados`, "var(--green)")}
    ${kpi("Média score", s.media_score || 0, `novos: ${s.por_status?.novo || 0} · análise: ${s.por_status?.em_analise || 0}`)}`;

  if (!data.items.length) {
    $("#cura-list").innerHTML = `<div class="empty">Nenhum item na curadoria com esses filtros.<br><small>Garimpe no Radar ou use “Garimpar e curar” acima.</small></div>`;
    return;
  }

  $("#cura-list").innerHTML = data.items.map(item => {
    const v = item.video || {};
    const cur = item.curadoria || {};
    const enr = item.enriquecimento || {};
    const meta = PF_META[v.platform] || PF_META.tiktok;
    const st = CURA_STATUS[item.status] || CURA_STATUS.novo;
    const sel = state.curadoria.selected.has(item.id);
    return `<div class="card" style="margin-bottom:10px;border-left:3px solid ${st.color === 'green' ? 'var(--green)' : st.color === 'red' ? 'var(--red)' : st.color === 'cyan' ? 'var(--cyan)' : 'var(--line)'};${sel ? 'outline:2px solid var(--gold)' : ''}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
        <div style="display:flex;gap:10px;align-items:center">
          <input type="checkbox" ${sel ? 'checked' : ''} onchange="curaToggleSel('${item.id}')" style="width:18px;height:18px" />
          <div style="width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,${meta.grad[0]},${meta.grad[1]});color:#fff;font-weight:800">${meta.label[0]}</div>
          <div>
            <div style="font-weight:700;font-size:13.5px;line-height:1.3">${esc(v.title || '(sem título)')}</div>
            <div style="font-size:11.5px;color:var(--muted)">${esc(v.handle || v.author)} · ${timeAgoH(v.age_hours)} · ${fmtNum(v.views)} views · <span class="badge ${st.color}">${st.icon} ${st.label}</span> <span class="src-badge src-${v.source || 'demo'}">${v.source || 'demo'}</span></div>
            <div style="font-size:11px;color:var(--faint);margin-top:2px">query: ${esc(item.query_origem || '—')} · score cura: <b style="color:var(--gold)">${cur.score_curadoria ?? v.viral_score}</b> (orig ${cur.score_original ?? v.viral_score} ${cur.score_mod ? (cur.score_mod>0?`+${cur.score_mod}`:cur.score_mod) : ''}) · ${esc((cur.reasons || []).slice(0,2).join(' · '))}</div>
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">${scoreRing(cur.score_curadoria ?? v.viral_score ?? 0, 38)}</div>
      </div>
      ${enr.hooks?.length ? `<div class="tags-row" style="margin-top:8px">${enr.hooks.slice(0,2).map(h => `<span class="mini-tag">🪝 ${esc(typeof h === 'string' ? h : h.hook || '')}</span>`).join("")}</div>` : ""}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
        <button class="btn small primary" onclick="curaDecide('${item.id}','aprovado')">✅ Aprovar</button>
        <button class="btn small" onclick="curaDecide('${item.id}','em_analise')">🔍 Análise</button>
        <button class="btn small" onclick="curaDecide('${item.id}','rejeitado')">❌ Rejeitar</button>
        <button class="btn small ghost" onclick="curaEnrich('${item.id}')">✨ Enriquecer IA</button>
        <button class="btn small ghost" onclick="curaOpen('${item.id}')">👁 Detalhes</button>
        <button class="btn small danger" onclick="curaDelete('${item.id}')">🗑</button>
      </div>
    </div>`;
  }).join("");

  updateBulkBar();
}

function curaToggleSel(id) {
  if (state.curadoria.selected.has(id)) state.curadoria.selected.delete(id);
  else state.curadoria.selected.add(id);
  updateBulkBar();
  // re-render checkbox state without full reload? just update bar
  const el = document.getElementById("cura-sel-count");
  if (el) el.textContent = state.curadoria.selected.size;
}
function curaClearSel() { state.curadoria.selected.clear(); updateBulkBar(); loadCuradoria(); }
function updateBulkBar() {
  const bar = $("#cura-bulk");
  const count = state.curadoria.selected.size;
  if (bar) {
    bar.style.display = count ? "block" : "none";
    const c = $("#cura-sel-count");
    if (c) c.textContent = count;
  }
}

async function curaDecide(id, decision) {
  try {
    await api(`/curation/items/${id}/decision`, { method: "POST", body: { decision, notas: "", por: "humano" } });
    toast(`${CURA_STATUS[decision]?.icon || ''} ${decision} ✔`);
    state.curadoria.selected.delete(id);
    loadCuradoria();
    loadCuradoriaOutliers();
  } catch (e) { toast(e.message, true); }
}
async function curaBulk(decision) {
  const ids = [...state.curadoria.selected];
  if (!ids.length) return toast("Nenhum selecionado", true);
  try {
    const r = await api("/curation/bulk-decision", { method: "POST", body: { ids, decision, notas: "bulk via UI" } });
    toast(`${r.alterados} itens → ${decision} ✔`);
    state.curadoria.selected.clear();
    loadCuradoria();
    loadCuradoriaOutliers();
  } catch (e) { toast(e.message, true); }
}
async function curaEnrich(id) {
  try {
    toast("Enriquecendo com IA…");
    await api(`/curation/items/${id}/auto-enrich`, { method: "POST" });
    toast("Enriquecido ✨");
    loadCuradoria();
  } catch (e) { toast(e.message, true); }
}
async function curaDelete(id) {
  if (!confirm("Remover este item da curadoria?")) return;
  try {
    await api(`/curation/items/${id}`, { method: "DELETE" });
    toast("Removido");
    state.curadoria.selected.delete(id);
    loadCuradoria();
  } catch (e) { toast(e.message, true); }
}
async function curaOpen(id) {
  const item = (state.curadoria.lastData || []).find(i => i.id === id) || await api(`/curation/queue?q=${id}`).then(d => d.items[0]).catch(() => null);
  if (!item) return toast("Item não encontrado", true);
  const v = item.video || {};
  const cur = item.curadoria || {};
  const enr = item.enriquecimento || {};
  openModal(`
    <span class="badge ${CURA_STATUS[item.status]?.color || 'gray'}">${CURA_STATUS[item.status]?.icon || ''} ${item.status}</span>
    <span class="badge gold">score cura ${cur.score_curadoria ?? v.viral_score}</span>
    <h2 style="margin-top:10px">${esc(v.title)}</h2>
    <div style="color:var(--muted);font-size:13px">${esc(v.handle || v.author)} · ${PF_META[v.platform]?.label || v.platform} · ${fmtNum(v.views)} views · ${v.engagement}% engaj.</div>
    <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
      <span class="badge gray">origem: ${esc(item.query_origem)} · ${esc(item.source)}</span>
      ${v.url ? `<a class="btn small ghost" href="${esc(v.url)}" target="_blank">↗ Abrir original</a>` : ""}
      <button class="btn small" onclick='sendToFabrica(${jattr(v.title)}, ${jattr(v.title + " - " + (v.hashtags||[]).join(" "))})'>🎬 Gerar vídeo</button>
    </div>
    <div class="divider"></div>
    <h3>Diagnóstico da curadoria</h3>
    <div style="font-size:13px;line-height:1.6;color:var(--muted)">${(cur.reasons || []).map(r => `• ${esc(r)}`).join("<br>") || "—"}</div>
    ${enr.hooks?.length ? `<div class="divider"></div><h3>🪝 Hooks IA</h3>${enr.hooks.map((h,i) => `<div class="hook-item"><span class="n">${i+1}</span><div>${esc(typeof h==='string'?h:h.hook||'')}</div></div>`).join("")}` : ""}
    ${enr.analise ? `<div class="divider"></div><h3>🧪 Análise Viral Lab</h3><div style="font-size:13px;color:var(--muted)">Outlier ${enr.analise.outlier_score} · ${esc(enr.analise.veredito||'')} <br><br>Formato: ${esc(enr.analise.formato_detectado||'')} <br>Hook: ${esc(enr.analise.hook_detectado||'')}</div>` : ""}
    <div class="divider"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn primary small" onclick="curaDecide('${item.id}','aprovado');closeModal()">✅ Aprovar</button>
      <button class="btn small" onclick="curaDecide('${item.id}','em_analise');closeModal()">🔍 Em análise</button>
      <button class="btn small danger" onclick="curaDecide('${item.id}','rejeitado');closeModal()">❌ Rejeitar</button>
      <button class="btn small" onclick="curaEnrich('${item.id}')">✨ Enriquecer IA</button>
    </div>
  `);
}

async function loadCuradoriaOutliers() {
  try {
    const data = await api("/curation/outliers?min_score=75&limit=8");
    $("#cura-outliers").innerHTML = data.outliers.length ? data.outliers.map(it => {
      const v = it.video || {};
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px dashed var(--line-soft)">
        <div><b style="font-size:12.5px">${esc(v.title?.slice(0,50))}</b><br><small style="color:var(--muted)">${esc(v.handle||v.author)} · ${fmtNum(v.views)} views</small></div>
        <div style="display:flex;gap:6px;align-items:center">${scoreRing(it.curadoria?.score_curadoria||v.viral_score,34)}<button class="btn small primary" onclick="curaDecide('${it.id}','aprovado')">✅</button></div>
      </div>`;
    }).join("") : `<div class="empty">Nenhum outlier ≥75 no momento</div>`;
  } catch {}
}
async function loadCuradoriaRulesMini() {
  try {
    const data = await api("/curation/rules");
    const r = data.rules;
    $("#cura-rules-mini").innerHTML = `
      <div style="font-size:12.5px;line-height:1.7;color:var(--muted)">
        min score: <b>${r.min_viral_score}</b> · min views: <b>${fmtNum(r.min_views)}</b> · engaj: <b>${r.min_engagement}%</b><br>
        max idade: <b>${r.max_age_hours}h</b> · plataforma: <b>${r.required_platform}</b><br>
        blacklist: ${(r.blacklist_keywords||[]).slice(0,4).map(k=>`<span class="mini-tag">${esc(k)}</span>`).join("")} ${r.blacklist_keywords?.length>4?'…':''}<br>
        auto-aprova: ${r.auto_approve_enabled?`<span class="badge green">ativo ≥${r.auto_approve_score}</span>`:`<span class="badge gray">desativado</span>`}
      </div>
      <button class="btn small" style="margin-top:8px" onclick="openCuraRules()">⚙️ Editar regras</button>`;
  } catch {}
}
async function openCuraRules() {
  const data = await api("/curation/rules");
  const r = data.rules;
  openModal(`
    <h2>⚙️ Regras de curadoria</h2>
    <p style="color:var(--muted);font-size:13px;margin:6px 0 14px">Defina filtros automáticos. Itens bloqueados vão para rejeitados; outliers podem auto-aprovar.</p>
    <div class="grid cols-2">
      <div class="field"><label>Min viral score</label><input id="rule-minscore" type="number" value="${r.min_viral_score}" /></div>
      <div class="field"><label>Min views</label><input id="rule-minviews" type="number" value="${r.min_views}" /></div>
      <div class="field"><label>Min engajamento %</label><input id="rule-mineng" type="number" step="0.1" value="${r.min_engagement}" /></div>
      <div class="field"><label>Max idade (horas)</label><input id="rule-maxage" type="number" value="${r.max_age_hours}" /></div>
      <div class="field"><label>Plataforma exigida</label><select id="rule-pf"><option value="all" ${r.required_platform==='all'?'selected':''}>Todas</option><option value="tiktok" ${r.required_platform==='tiktok'?'selected':''}>TikTok</option><option value="instagram" ${r.required_platform==='instagram'?'selected':''}>Instagram</option><option value="youtube" ${r.required_platform==='youtube'?'selected':''}>YouTube</option></select></div>
      <div class="field"><label>Auto-aprovar ≥ score</label><input id="rule-autoapp" type="number" value="${r.auto_approve_score}" /></div>
      <div class="field"><label>Auto-rejeitar ≤ score</label><input id="rule-autorej" type="number" value="${r.auto_reject_score}" /></div>
      <div class="field"><label>Auto-aprovação ativa?</label><select id="rule-autoon"><option value="0" ${!r.auto_approve_enabled?'selected':''}>Desativado</option><option value="1" ${r.auto_approve_enabled?'selected':''}>Ativo</option></select></div>
    </div>
    <div class="field" style="margin-top:12px"><label>Blacklist keywords (separadas por vírgula)</label><input id="rule-black" value="${esc((r.blacklist_keywords||[]).join(", "))}" /></div>
    <div class="field" style="margin-top:10px"><label>Whitelist keywords (boost +10)</label><input id="rule-white" value="${esc((r.whitelist_keywords||[]).join(", "))}" /></div>
    <div class="field" style="margin-top:10px"><label>Tags prioritárias (boost +8)</label><input id="rule-tags" value="${esc((r.tags_prioritarias||[]).join(", "))}" /></div>
    <div style="margin-top:16px;display:flex;gap:8px"><button class="btn primary" onclick="saveCuraRules()">💾 Salvar regras</button><button class="btn" onclick="closeModal()">Fechar</button></div>
  `);
}
async function saveCuraRules() {
  const toList = (s) => s.split(",").map(x=>x.trim()).filter(Boolean);
  const body = {
    min_viral_score: +$("#rule-minscore").value || 0,
    min_views: +$("#rule-minviews").value || 0,
    min_engagement: parseFloat($("#rule-mineng").value) || 0,
    max_age_hours: +$("#rule-maxage").value || 720,
    required_platform: $("#rule-pf").value,
    auto_approve_score: +$("#rule-autoapp").value || 85,
    auto_reject_score: +$("#rule-autorej").value || 15,
    auto_approve_enabled: $("#rule-autoon").value === "1",
    blacklist_keywords: toList($("#rule-black").value),
    whitelist_keywords: toList($("#rule-white").value),
    tags_prioritarias: toList($("#rule-tags").value),
  };
  try {
    await api("/curation/rules", { method: "POST", body: { rules: body } });
    toast("Regras salvas ✔");
    closeModal();
    loadCuradoriaRulesMini();
    loadCuradoria();
  } catch (e) { toast(e.message, true); }
}
window.openCuraRules = openCuraRules;
window.saveCuraRules = saveCuraRules;
window.curaToggleSel = curaToggleSel;
window.curaClearSel = curaClearSel;
window.curaDecide = curaDecide;
window.curaBulk = curaBulk;
window.curaEnrich = curaEnrich;
window.curaDelete = curaDelete;
window.curaOpen = curaOpen;

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
  $("#ml-real")?.remove();
  const params = new URLSearchParams({ sort: $("#prod-sort").value, limit: "18" });
  const q = $("#prod-q").value.trim();
  if (q) params.set("q", q);
  if (prodCat) params.set("category", prodCat);
  const data = await api("/products?" + params);

  if (data.mercadolivre?.length) {
    const sig = data.ml_signal || {};
    const card = document.createElement("div");
    card.id = "ml-real";
    card.className = "card";
    card.style.marginBottom = "14px";
    card.innerHTML = `
      <h3>🛒 Mercado real — Mercado Livre Brasil <span class="badge green">dados reais · sem chave</span></h3>
      <div class="form-row" style="margin-bottom:10px">
        <span class="badge gold">mediana ${fmtBRL(sig.price_median || 0)}</span>
        <span class="badge cyan">+${fmtNum(sig.total_sold || 0)} vendidos (amostra)</span>
        <span class="badge violet">nota média ★ ${sig.avg_rating || "—"}</span>
        <small style="color:var(--faint)">use como referência de preço/demanda para o GMV estimado</small>
      </div>
      <div class="grid cols-3">${data.mercadolivre.slice(0, 6).map(m => `
        <a class="ml-card" href="${esc(m.permalink)}" target="_blank" rel="noopener">
          <img src="${esc(m.thumbnail)}" alt="" loading="lazy"
               onerror="this.style.visibility='hidden'" />
          <div>
            <div class="ml-title">${esc(m.title)}</div>
            <div style="margin-top:4px"><b>${fmtBRL(m.price)}</b>
              <small style="color:var(--muted)">· ${fmtNum(m.sold_quantity)} vend. · ★${m.rating || "—"}</small>
              ${m.free_shipping ? '<small style="color:var(--green)"> · frete grátis</small>' : ""}
            </div>
          </div>
        </a>`).join("")}
      </div>`;
    $("#prod-table").parentNode.insertBefore(card, $("#prod-table"));
  }

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
        <button class="btn small" onclick="copyText(${jattr(s.narracao)}, 'Narração copiada!')">📋 Copiar narração</button>
        <button class="btn small" onclick='sendToVoice(${jattr(s.narracao)})'>🎙️ Enviar pro Voice Studio</button>
        <button class="btn small primary" onclick='sendToFabrica(${jattr(s.titulo_sugerido || "vídeo")}, ${jattr(s.narracao)})'>🎬 Gerar vídeo na Fábrica</button>
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
          ${a.video_real ? `
          <div style="display:flex;gap:12px;background:var(--bg-soft);border:1px solid var(--green-soft);
            border-radius:12px;padding:10px;margin-bottom:14px;align-items:center">
            ${a.video_real.thumb ? `<img src="${esc(a.video_real.thumb)}" style="width:96px;border-radius:8px"
              onerror="this.style.display='none'" />` : ""}
            <div><span class="badge green">dados reais · oEmbed oficial</span>
              <div style="font-weight:700;margin-top:6px;font-size:13.5px">${esc(a.video_real.title)}</div>
              <small style="color:var(--muted)">${esc(a.video_real.author)} · ${a.video_real.platform}</small>
            </div>
          </div>` : ""}
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

// ============================================================ FÁBRICA DE VÍDEOS / IMAGENS / MISTA — ComfyUI RunPod
const JOB_STATUS = {
  fila: ["⏳", "Fila", "status-fila"],
  enviado: ["📡", "Enviado ao n8n", "status-enviado"],
  processando: ["🎞️", "Renderizando (RunPod)", "status-processando"],
  pronto: ["✅", "Pronto", "status-pronto"],
  erro: ["⚠️", "Erro", "status-erro"],
};
const JOB_TIPO_LABEL = { video: "🎬 Vídeo", imagem: "🖼️ Imagem", misto: "🎞️+🖼️ Misto" };

async function viewFabrica() {
  const pre = JSON.parse(sessionStorage.getItem("fabrica-prefill") || "null");
  sessionStorage.removeItem("fabrica-prefill");
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Fábrica ComfyUI 🎬🖼️</h1>
      <p>Produção <b>imagem, vídeo ou mista</b>: o job vai para o <b>n8n router</b> (<code>mineraai-fabrica-job</code>) que roteia para
      <code>mineraai-imagem-job</code> / <code>video-job</code> / <code>misto-job</code>, injeta seu <b>roteiro</b> no workflow ComfyUI API e chama <b>RunPod Serverless</b>.
      Retorna <code>video_url</code> + <code>images[]</code>. Configure webhooks em <span class="link-gold" onclick="location.hash='#/apis'">APIs & Conexões</span>.</p>
    </div></div>
    <div class="grid cols-2">
      <div class="card">
        <h3>Nova produção — ComfyUI</h3>
        <div class="form-row" style="margin-bottom:10px">
          <div class="field grow"><label>Tipo de geração</label>
            <select id="fab-tipo">
              <option value="video" ${pre?.tipo==='video'?'selected':''}>🎬 Vídeo (AnimateDiff / LTX)</option>
              <option value="imagem" ${pre?.tipo==='imagem'?'selected':''}>🖼️ Imagem (SDXL / Realistic)</option>
              <option value="misto" ${pre?.tipo==='misto'?'selected':''}>🎞️+🖼️ Misto (kit UGC: 4 imgs + 1 vídeo)</option>
            </select></div>
          <div class="field grow"><label>Produto / tema</label>
            <input id="fab-product" placeholder="ex: garrafa térmica premium" value="${esc(pre?.product || "")}" /></div>
        </div>
        <div class="field" style="margin-bottom:10px"><label>Prompt visual / roteiro (gancho + cenas)</label>
          <textarea id="fab-prompt" rows="4" placeholder="Descreva as cenas ou cole o roteiro do Estúdio IA / Curadoria. Ex: GANCHO: close garrafa com gelo...">${esc(pre?.prompt || "")}</textarea></div>
        <div class="field" style="margin-bottom:10px"><label>Roteiro avançado (JSON opcional) — {hook, cenas:[{nome,descricao,prompt,duracao}], narracao}</label>
          <textarea id="fab-roteiro" rows="5" placeholder='{"hook":"Pare de comprar garrafas que não gelam!","cenas":[{"nome":"GANCHO","descricao":"close garrafa","prompt":"close-up premium bottle with ice, studio light","duracao":2},{"nome":"DEMO","descricao":"demonstra gelo 24h","prompt":"bottle pouring ice water, kitchen counter","duracao":3},{"nome":"CTA","descricao":"preço e CTA","prompt":"bottle on table with price tag, lifestyle","duracao":2}],"narracao":"Essa garrafa mantém gelo 24h..."}'>${esc(pre?.roteiro ? JSON.stringify(pre.roteiro,null,2) : "")}</textarea></div>
        <div class="form-row" style="margin-bottom:14px">
          <div class="field grow"><label>Estilo</label>
            <select id="fab-style">
              <option value="ugc">UGC (criador real)</option>
              <option value="produto">Showcase de produto</option>
              <option value="dark">Dark / canal dark</option>
              <option value="cinematic">Cinematográfico</option>
              <option value="anime">Anime / ilustrado</option>
            </select></div>
          <div class="field grow"><label>Duração vídeo (s)</label>
            <input id="fab-dur" type="number" value="6" min="2" max="30" /></div>
          <div class="field grow"><label>Qtd imagens (se imagem/misto)</label>
            <input id="fab-qtd" type="number" value="3" min="1" max="4" /></div>
        </div>
        <div class="form-row">
          <button class="btn primary" id="fab-go">🚀 Enviar para ComfyUI</button>
          <button class="btn" id="fab-broll">🎞️ Buscar B-roll (Pexels)</button>
          <button class="btn ghost" id="fab-exemplo-misto">📦 Exemplo misto UGC</button>
        </div>
        <div id="fab-broll-out" style="margin-top:12px"></div>
        <div style="margin-top:10px;font-size:11px;color:var(--faint)">Payload enviado: {tipo, product, prompt, style, duration, roteiro:{hook,cenas,narracao}, prompts:[...], qtd_imagens}. n8n injeta em CLIPTextEncode + KSampler do workflow ComfyUI.</div>
      </div>
      <div class="card">
        <h3>Como funciona o pipeline ComfyUI</h3>
        <div style="font-size:12.5px;line-height:1.9;color:var(--muted)">
          <b style="color:var(--text)">1. Router</b> <code>mineraai-fabrica-job</code> recebe {tipo} → roteia para fábrica correta<br>
          <b style="color:var(--text)">2. Fábrica Imagem</b> monta N CLIPTextEncode+KSampler+VAEDecode+SaveImage (batch dinâmico)<br>
          <b style="color:var(--text)">3. Fábrica Vídeo</b> monta AnimateDiff 16f ou LTX 121f, injeta STYLE_PREFIX + roteiro<br>
          <b style="color:var(--text)">4. Fábrica Mista</b> monta 4 imagens (CAPA/HOOK/DEMO/CTA) + 1 vídeo AnimateDiff 24f<br>
          <b style="color:var(--text)">5.</b> <code>/run</code> → <code>/status</code> polling com retry → extrai <code>video_url</code> + <code>images[]</code><br>
          <b style="color:var(--text)">6.</b> callback MineraAI <code>/api/fabrica/callback/{job_id}</code> com token<br><br>
          <span class="badge cyan">Workflows ComfyUI API</span> em <code>comfyui/workflows/</code>:<br>
          • <code>workflow-imagem-sdxl.json</code> (768x1344 9:16)<br>
          • <code>workflow-imagem-produto.json</code> (batch 3 UGC)<br>
          • <code>workflow-video-animatediff.json</code> (512x768 16f + VHS_VideoCombine)<br>
          • <code>workflow-video-ltx.json</code> (576x1024 121f 24fps LTX-Video)<br>
          • <code>workflow-misto-ugc.json</code> (3 imgs + 1 vídeo)<br>
          • <code>workflow-misto-curadoria.json</code> (capa + 3 + vídeo curado)<br><br>
          📦 Importe <code>n8n/fabrica-*-comfyui-runpod.json</code> + <code>fabrica-router</code> no n8n.
        </div>
      </div>
    </div>
    <div class="section-title">Fila de produção ComfyUI <button class="btn small" onclick="loadJobs()">↻ Atualizar</button></div>
    <div class="card"><div id="fab-jobs">…</div></div>`;

  $("#fab-go").onclick = createJob;
  $("#fab-exemplo-misto").onclick = () => {
    $("#fab-tipo").value = "misto";
    $("#fab-product").value = $("#fab-product").value || "garrafa térmica premium";
    $("#fab-roteiro").value = JSON.stringify({
      hook: "Pare de comprar garrafas que não mantém gelo!",
      cenas: [
        { nome: "CAPA", descricao: "thumbnail scroll-stopper", prompt: "premium stainless steel bottle with ice cubes, bold text overlay mockup, studio lighting, 9:16 vertical", duracao: 1 },
        { nome: "GANCHO", descricao: "close gelo caindo", prompt: "close-up ice cubes falling into premium black bottle, slow motion, kitchen background blur", duracao: 2 },
        { nome: "DEMO", descricao: "prova 24h gelado", prompt: "woman holding cold bottle after 24h, condensation droplets, lifestyle kitchen, UGC style", duracao: 3 },
        { nome: "CTA", descricao: "oferta e CTA", prompt: "bottle on wooden table with price tag R$ 79,90, buy now button overlay, cozy home", duracao: 2 }
      ],
      narracao: "Essa garrafa mantém gelo por 24 horas de verdade. Olha isso. Comprei por 79 e já economizei 200 em bebidas. Link na bio."
    }, null, 2);
    toast("Exemplo misto preenchido — clique em Enviar");
  };
  $("#fab-broll").onclick = async () => {
    const q = $("#fab-product").value.trim() || "produto";
    $("#fab-broll-out").innerHTML = `<small style="color:var(--muted)">Buscando…</small>`;
    const r = await api("/fabrica/broll?q=" + encodeURIComponent(q));
    $("#fab-broll-out").innerHTML = r.ok
      ? `<div class="grid cols-3">${r.items.slice(0, 6).map(b => `
          <a href="${esc(b.video_file || b.url)}" target="_blank" rel="noopener">
            <img src="${esc(b.image)}" style="width:100%;border-radius:8px;aspect-ratio:16/9;object-fit:cover"
              onerror="this.parentNode.style.display='none'" />
            <small style="color:var(--faint)">${b.duration || ""}s · ${esc(b.user)}</small></a>`).join("")}</div>`
      : `<small style="color:var(--faint)">${esc(r.message)}</small>`;
  };
  loadJobs();
}

async function createJob() {
  const product = $("#fab-product").value.trim();
  if (!product) return toast("Informe o produto/tema", true);
  let roteiro = null;
  const roteiroRaw = $("#fab-roteiro").value.trim();
  if (roteiroRaw) {
    try { roteiro = JSON.parse(roteiroRaw); }
    catch { 
      // tenta interpretar como texto livre -> cria cenas a partir do prompt
      roteiro = { hook: $("#fab-prompt").value.trim().slice(0,120), cenas: [], narracao: roteiroRaw };
    }
  }
  const body = {
    tipo: $("#fab-tipo").value,
    product,
    prompt: $("#fab-prompt").value.trim(),
    style: $("#fab-style").value,
    duration: +$("#fab-dur").value || 6,
    qtd_imagens: +$("#fab-qtd").value || 3,
    roteiro,
    prompts: roteiro?.cenas?.map(c=>c.prompt) || null,
  };
  const r = await api("/fabrica/jobs", { method: "POST", body });
  const st = r.job.status;
  toast(st === "enviado" ? `Job ${body.tipo} enviado ao n8n router 🚀`
    : st === "erro" ? "n8n inacessível — configure o webhook em APIs"
    : `Job ${body.tipo} na fila — configure o webhook do n8n para disparar`);
  loadJobs();
}
window.createJob = createJob;

async function loadJobs() {
  const el = $("#fab-jobs");
  if (!el) return;
  const data = await api("/fabrica/jobs");
  if (!data.jobs.length) {
    el.innerHTML = `<div class="empty">Nenhum job ainda — crie o primeiro vídeo/imagem ao lado.
      ${data.webhook_configurado ? "" : "<br>⚠️ Webhook do n8n não configurado (aba APIs & Conexões). Configure N8N_WEBHOOK_URL apontando para <code>mineraai-fabrica-job</code> (router)."}<br>
      <small style="color:var(--faint)">Dica: use tipo <b>misto</b> para receber kit 4 imagens + 1 vídeo (ComfyUI workflow-misto-curadoria)</small></div>`;
    return;
  }
  el.innerHTML = `<table class="table">
    <thead><tr><th>Job</th><th>Produto</th><th>Tipo</th><th>Status</th><th>Custo</th><th>Prévia</th><th></th></tr></thead>
    <tbody>${data.jobs.map(j => {
      const [ico, lb, cls] = JOB_STATUS[j.status] || ["•", j.status, ""];
      const tipo = j.tipo || (j.video_url && j.images?.length ? 'misto' : j.video_url ? 'video' : j.images?.length ? 'imagem' : 'video');
      const preview = j.status==='pronto' ? `
        ${j.video_url ? `<span class="badge cyan">🎬 vídeo</span>` : ``}
        ${j.images?.length ? `<span class="badge violet">🖼️ ${j.images.length} imgs</span>` : ``}
      ` : '';
      return `<tr>
        <td style="font-family:monospace;font-size:11px">${j.id.slice(0,8)}</td>
        <td><b>${esc(j.product)}</b><br><small style="color:var(--faint)">${j.created_at?.slice(0, 16).replace("T", " ")} · ${esc(j.style||'')} · ${j.duration||6}s</small></td>
        <td><span class="badge gray">${JOB_TIPO_LABEL[tipo] || tipo}</span></td>
        <td><span class="job-status ${cls}">${ico} ${lb}</span>
          ${j.error ? `<br><small style="color:var(--red)">${esc(j.error)}</small>` : ""}</td>
        <td class="num">${j.cost_usd != null ? "$" + Number(j.cost_usd).toFixed(4) : "—"}</td>
        <td>${preview}</td>
        <td style="white-space:nowrap">
          ${j.status === "pronto" && (j.video_url || j.images?.length)
            ? `<button class="btn small primary" onclick="playJob(${jattr(j)})">▶ Ver</button>` : ""}
          <button class="btn small danger" onclick="delJob('${j.id}')">✕</button>
        </td></tr>`;
    }).join("")}</tbody></table>`;
  if (data.jobs.some(j => ["fila", "enviado", "processando"].includes(j.status))) {
    fabricaTimer = setTimeout(loadJobs, 7000);
  }
}
window.loadJobs = loadJobs;

window.playJob = (job) => {
  const tipo = job.tipo || (job.video_url && job.images?.length ? 'misto' : job.video_url ? 'video' : 'imagem');
  const imagesHtml = (job.images||[]).map((img,i)=>{
    const url = typeof img==='string' ? img : img.url;
    const prompt = typeof img==='string' ? '' : (img.prompt||img.cena||'');
    return `<div class="card" style="padding:6px">
      <img src="${esc(url)}" style="width:100%;border-radius:8px;aspect-ratio:9/16;object-fit:cover" loading="lazy" />
      <small style="color:var(--faint);display:block;margin-top:4px">${esc(prompt).slice(0,80)}</small>
      <a class="btn small ghost" href="${esc(url)}" target="_blank" style="margin-top:4px">↗ Abrir</a>
    </div>`;
  }).join("");
  openModal(`
  <span class="badge gray">${JOB_TIPO_LABEL[tipo]||tipo}</span> <span class="badge gold">${esc(job.product)}</span>
  ${job.cost_usd!=null?`<span class="badge violet">custo $${Number(job.cost_usd).toFixed(4)}</span>`:''}
  <h2 style="margin-top:8px">${esc(job.product)} — ${tipo}</h2>
  ${job.video_url ? `
    <video controls autoplay style="width:100%;border-radius:12px;margin-top:12px;background:#000;max-height:60vh"
      src="${esc(job.video_url)}"></video>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
      <a class="btn primary" href="${esc(job.video_url)}" download>⬇ Baixar MP4</a>
      <button class="btn" onclick="copyText(${jattr(job.video_url)}, 'Link vídeo copiado!')">📋 Copiar link vídeo</button>
    </div>` : `<div class="empty" style="margin-top:12px">Sem vídeo — job de imagem</div>`}
  ${job.images?.length ? `
    <div class="divider"></div>
    <h3>🖼️ Imagens geradas (${job.images.length}) — ComfyUI</h3>
    <div class="grid cols-3" style="margin-top:10px">${imagesHtml}</div>
    <button class="btn small" style="margin-top:10px" onclick="copyText(${jattr((job.images||[]).map(i=>typeof i==='string'?i:i.url).join('\\n'))}, 'Links copiados!')">📋 Copiar todos links imagens</button>
  ` : ``}
  ${job.prompt ? `<div class="divider"></div><small style="color:var(--muted)"><b>Prompt:</b> ${esc(job.prompt)}</small>` : ``}
  ${job.roteiro ? `<div style="margin-top:8px"><small style="color:var(--muted)"><b>Roteiro:</b> hook ${esc(job.roteiro.hook||'')} · ${job.roteiro.cenas?.length||0} cenas</small></div>` : ``}
  `);
};

window.delJob = async (id) => { await api(`/fabrica/jobs/${id}`, { method: "DELETE" }); loadJobs(); };

window.sendToFabrica = (product, prompt, tipo='video', roteiro=null) => {
  sessionStorage.setItem("fabrica-prefill", JSON.stringify({ product, prompt, tipo, roteiro }));
  location.hash = "#/fabrica";
};

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
    { k: "coleta", icon: "🕷️", fields: [],
      docs: "https://github.com/D4Vinci/Scrapling",
      how: "Sem chave nenhuma: o Scrapling (open source) coleta dados públicos reais das páginas de busca — YouTube direto, TikTok/Instagram quando acessíveis — com fingerprint TLS de Chrome. 1 requisição por busca, timeouts curtos. Desative abaixo se preferir apenas APIs oficiais + demo.",
      extra: "toggle" },
    { k: "fontes_gratuitas", icon: "🆓", fields: [["PEXELS_API_KEY", "Pexels API key (B-roll grátis, opcional)", "password"]],
      docs: "https://www.pexels.com/api/",
      how: "Sempre ativas e sem chave: Mercado Livre (produtos reais BR), Reddit (pauta viral), Google Suggest (demanda de busca), Google Trends (termos em alta) e oEmbed YouTube/TikTok (metadados reais de links). A chave Pexels libera B-roll gratuito na Fábrica de Vídeos.",
      test: "fontes" },
    { k: "automacao", icon: "🤖", fields: [["N8N_WEBHOOK_URL", "URL do webhook n8n (Fábrica de Vídeos)", "text"],
      ["N8N_TOKEN", "Token de segurança do callback", "password"],
      ["MINERAAI_PUBLIC_URL", "URL pública do MineraAI (p/ callbacks)", "text"]],
      docs: "https://docs.n8n.io/",
      how: "Cole aqui a URL do webhook do workflow 'Fábrica de Vídeos' (arquivos importáveis em n8n/ no repositório). O n8n orquestra o ComfyUI no RunPod serverless e devolve o MP4 via callback protegido pelo token. MINERAAI_PUBLIC_URL é o endereço que o n8n usa para chamar de volta.",
      extra: "n8n" },
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
      ${d.extra === "toggle" ? `
        <div class="form-row" style="margin-top:10px">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer">
            <input type="checkbox" id="set-SCRAPLING_ENABLED" style="width:auto" ${(cfg.settings.SCRAPLING_ENABLED ?? "1") !== "0" ? "checked" : ""} />
            Coleta pública ativada (fonte: <span class="src-badge src-coleta">coleta real</span>)
          </label>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer;color:var(--muted)">
            <input type="checkbox" id="set-SCRAPLING_STEALTHY" style="width:auto" ${(cfg.settings.SCRAPLING_STEALTHY ?? "0") === "1" ? "checked" : ""} />
            Modo stealth (requer <code>scrapling install</code>)
          </label>
        </div>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
        ${d.fields.length || d.extra==="toggle" ? `<button class="btn primary small" onclick="saveProvider('${d.k}', ${JSON.stringify(d.fields.map(f => f[0]).concat(d.extra === "toggle" ? ["SCRAPLING_ENABLED", "SCRAPLING_STEALTHY"] : []))})">💾 Salvar</button>` : ""}
        ${d.test ? `<button class="btn small" onclick="testProvider('${d.test}')">🔍 Testar conexão</button>` : d.k!=="curadoria" ? `<button class="btn small" onclick="testProvider('${d.k}')">🔍 Testar conexão</button>` : ""}
        <a class="btn small ghost" href="${d.docs}" target="_blank" rel="noopener">📖 ${d.k === "coleta" ? "Repositório" : d.k === "automacao" ? "Docs n8n" : d.k === "curadoria" ? "Ver workflows" : "Como obter"}</a>
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
  fields.forEach(f => {
    const el = $(`#set-${f}`);
    if (!el) return;
    if (el.type === "checkbox") { patch[f] = el.checked ? "1" : "0"; return; }
    const v = el.value?.trim(); if (v) patch[f] = v;
  });
  if (!Object.keys(patch).length) return toast("Preencha ao menos um campo", true);
  await api("/settings", { method: "POST", body: { settings: patch } });
  toast("Configurações salvas ✔");
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
