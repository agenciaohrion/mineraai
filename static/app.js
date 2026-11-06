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
  const key = localStorage.getItem("mineraai_api_key");
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const d = body.detail || {};
    let msg = (typeof d === "string" ? d : (d.error || d.msg)) || body.error || res.statusText;
    if (d.credits_needed) msg += ` — precisa ${d.credits_needed}, você tem ${d.credits_remaining}`;
    if (d.daily_limit) msg += ` (limite diário: ${d.daily_limit})`;
    throw new Error(msg);
  }
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
const state = { status: null, lastSearch: null, me: null };

async function loadStatus() {
  try {
    state.status = await api("/status");
    const live = state.status.live.length;
    $("#modePill").innerHTML = live
      ? `Modo <b>híbrido</b> — ${live} API(s) oficial(is) conectada(s).`
      : `Modo <b>demonstração</b> — dados simulados. Conecte suas chaves em <b>APIs & Conexões</b>.`;
  } catch { $("#modePill").textContent = "Backend offline"; }
}

async function loadMe() {
  try {
    state.me = await api("/me");
    const plano = state.me.plano;
    const rest = plano.credits_remaining;
    $("#creditText").textContent = `${fmtNum(rest)}/${fmtNum(plano.credits_total)} créditos · ${plano.plan_name}`;
    $("#creditPill").classList.toggle("low", plano.credits_pct >= 85);
    $("#creditPill").title = `Plano ${plano.plan_name} · ${plano.credits_used} usados · `
      + `renova em ${plano.cycle_start} · ${plano.daily_remaining}/${plano.daily_limit} consultas hoje`;
  } catch { $("#creditText").textContent = "créditos indisponíveis"; }
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
      ${v.outlier_score >= 30 ? `<div class="outlier-tag" title="Outlier: ${v.outlier_ratio}x acima do baseline (${fmtNum(v.creator_baseline)} views)">🚀 ${v.outlier_score} · ${v.outlier_ratio}x</div>` : ""}
      <div class="score" title="Viral Score">${scoreRing(v.viral_score)}</div>
      ${v.duration ? `<span class="duration">${fmtDur(v.duration)}</span>` : ""}
    </div>
    <div class="vid-body">
      <div class="vid-title">${esc(v.title)}</div>
      <div class="vid-author">${esc(v.handle || v.author)} · ${timeAgoH(v.age_hours)}
        <span class="src-badge src-${v.source}">${{ oficial: "oficial", api: "oficial", virlo: "virlo", ingestao: "mineração", mineracao: "mineração", publicado: "publicado", demo: "demo" }[v.source] || v.source}</span></div>
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
  outliers: viewOutliers,
  agents: viewAgents,
  mineracao: viewMineracao,
  billing: viewBilling,
  lojas: viewLojas,
  produtos: viewProdutos,
  criadores: viewCriadores,
  lives: viewLives,
  nichos: viewNichos,
  studio: viewStudio,
  fabrica: viewFabrica,
  biblioteca: viewBiblioteca,
  publicacoes: viewPublicacoes,
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
      <p>O garimpo do dia: produtos quentes, lives faturando e nichos emergentes — tudo em um só painel.</p>
    </div></div>
    <div class="grid cols-4" id="kpis"></div>
    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>📦 Top produtos (GMV est. 30d)</h3><div id="dash-products">…</div></div>
      <div class="card"><h3>🔴 Lives faturando agora</h3><div id="dash-lives">…</div></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>🧭 Nichos com maior outlier score</h3><div id="dash-niches">…</div></div>
    <div class="card" style="margin-top:14px"><h3>📈 Termos em alta agora — Google Trends BR <span id="trends-fonte" class="badge gray"></span></h3><div id="dash-trends">…</div></div>`;

  const [prod, lives, niches, trends] = await Promise.all([
    api("/products?limit=6&sort=gmv"), api("/lives?limit=5"), api("/niches?limit=5"),
    api("/trends?limit=12").catch(() => ({ terms: [], fonte: "indisponível" })),
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
        <select id="radar-src" style="width:180px" title="Isola uma camada de dados. Em &quot;demonstração&quot; o resultado é simulado; em &quot;só oficial&quot; o demo nunca entra como reserva.">
          <option value="all">Todas as origens</option>
          <option value="oficial">Só oficial</option>
          <option value="virlo">Só Virlo</option>
          <option value="mineracao">Só mineração</option>
          <option value="demo">Só demonstração</option>
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
        <div class="card" style="margin-top:14px"><h3>💡 Ideias de pauta <span class="badge gray">Reddit + Google</span></h3><div id="radar-ideas">…</div></div>
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
    sort: $("#radar-sort").value, limit: "12", source: $("#radar-src").value,
  });
  state.lastSearch = { q };
  $("#radar-results").innerHTML = skeletonGrid(6);
  const data = await api("/search?" + params);
  const { source_breakdown: sb } = data;
  const real = (sb.oficial || 0) + (sb.virlo || 0) + (sb.ingestao || 0);
  const SRC = { all: "todas as origens", oficial: "só oficial", virlo: "só Virlo",
                mineracao: "só mineração", demo: "só demonstração" };
  const srcAtiva = data.source || "all";
  $("#radar-summary").innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <span class="badge gold">${data.total} vídeos encontrados</span>
      ${srcAtiva !== "all" ? `<span class="badge ${srcAtiva === "demo" ? "gray" : "cyan"}">origem: ${SRC[srcAtiva] || srcAtiva}</span>` : ""}
      <span class="badge green">oficial: ${sb.oficial}</span>
      ${sb.virlo ? `<span class="badge violet">virlo: ${sb.virlo}</span>` : ""}
      ${sb.ingestao ? `<span class="badge gold">mineração: ${sb.ingestao}</span>` : ""}
      ${sb.publicado ? `<span class="badge green">publicado: ${sb.publicado}</span>` : ""}
      <span class="badge violet">demo: ${sb.demo}</span>
      ${(data.errors || []).length ? `<span class="badge gray" title="${esc((data.errors || []).join(" · "))}">⚠ fontes com erro</span>` : ""}
      ${real === 0 ? '<small style="color:var(--muted)">— conecte chaves em <span class="link-gold" onclick="location.hash=&quot;#/apis&quot;">APIs & Conexões</span>, ligue a Virlo ou minere um Orbit</small>' : ""}
    </div>`;
  $("#radar-results").innerHTML = data.videos.length
    ? `<div class="vid-grid">${data.videos.map(videoCard).join("")}</div>`
    : `<div class="empty">${srcAtiva === "all"
        ? "Nenhum resultado. Tente outro termo."
        : `Nenhum vídeo em <b>${SRC[srcAtiva] || srcAtiva}</b> para este termo.
           A origem foi isolada a pedido — o demo não entra como reserva.
           <br><span class="link-gold" onclick="$('#radar-src').value='all'; runRadar();">buscar em todas as origens</span>`}</div>`;
  $("#radar-tags").innerHTML = data.top_hashtags.map(t => `
    <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:13px">
      <b style="color:var(--cyan)">${esc(t.tag)}</b><span class="num">${fmtNum(t.reach)}</span></div>`).join("") || "—";
  $("#radar-sounds").innerHTML = data.top_sounds.map(s => `
    <div style="padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:12.5px">
      🎵 ${esc(s.sound)}<br><small class="num" style="color:var(--muted)">alcance ${fmtNum(s.reach)}</small></div>`).join("") || "—";
  $("#radar-creators").innerHTML = data.top_creators.map(c => `
    <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line-soft);font-size:13px">
      <b>${esc(c.handle)}</b><span class="num" style="color:var(--muted)">${c.videos} víd · ${fmtNum(c.views)}</span></div>`).join("") || "—";

  // Ideias de pauta: Reddit (top real) + Google Suggest (demanda de busca)
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

  // Mercado Livre — dados REAIS de mercado BR (API pública oficial, grátis)
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

// ============================================================ FÁBRICA DE VÍDEOS
const JOB_STATUS = {
  fila: ["⏳", "Fila", "status-fila"],
  enviado: ["📡", "Enviado ao RunPod", "status-enviado"],
  processando: ["🎞️", "Renderizando (RunPod)", "status-processando"],
  pronto: ["✅", "Pronto", "status-pronto"],
  publicado: ["📤", "Publicado no YouTube", "status-pronto"],
  erro: ["⚠️", "Erro", "status-erro"],
};

async function viewFabrica() {
  const pre = JSON.parse(sessionStorage.getItem("fabrica-prefill") || "null");
  sessionStorage.removeItem("fabrica-prefill");
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Fábrica de Vídeos 🎬</h1>
      <p><b>RunPod direto</b>: o MineraAI chama o endpoint serverless do ComfyUI sem
      n8n no meio — uma requisição, sem webhook, sem callback.</p>
    </div></div>
    <div class="grid cols-2">
      <div class="card">
        <h3>Novo vídeo</h3>
        <div class="field" style="margin-bottom:10px"><label>Produto / tema</label>
          <input id="fab-product" placeholder="ex: garrafa térmica premium" value="${esc(pre?.product || "")}" /></div>
        <div class="field" style="margin-bottom:10px"><label>Prompt visual (roteiro, cenas, estética)</label>
          <textarea id="fab-prompt" rows="5" placeholder="Descreva as cenas ou cole o roteiro do Estúdio IA…">${esc(pre?.prompt || "")}</textarea></div>
        <div class="form-row" style="margin-bottom:14px">
          <div class="field grow"><label>Estilo</label>
            <select id="fab-style">
              <option value="dark">Dark / canal dark</option>
              <option value="cinematic">Cinematográfico</option>
              <option value="ugc">UGC (criador)</option>
              <option value="produto">Showcase de produto</option>
            </select></div>
          <div class="field grow"><label>Duração (s)</label>
            <input id="fab-dur" type="number" value="6" min="2" max="60" /></div>
          <div class="field grow"><label>Modalidade</label>
            <select id="fab-mode">
              <option value="sync">Sync — espera o resultado</option>
              <option value="async">Async — fila + polling</option>
            </select></div>
        </div>
        <div class="form-row">
          <button class="btn primary" id="fab-go">🚀 Renderizar no RunPod</button>
          <button class="btn" id="fab-broll">🎞️ Buscar B-roll (Pexels)</button>
          <button class="btn ghost" id="fab-health">🩺 Health do endpoint</button>
        </div>
        <div id="fab-broll-out" style="margin-top:12px"></div>
        <div id="fab-health-out" style="margin-top:12px"></div>
      </div>
      <div class="card">
        <h3>Conexão RunPod</h3>
        <div id="fab-runpod">…</div>
        <div style="font-size:13px;line-height:1.9;color:var(--muted);margin-top:12px">
          <b style="color:var(--text)">1.</b> MineraAI monta o grafo ComfyUI (template salvo ou padrão)<br>
          <b style="color:var(--text)">2.</b> <code>POST /v2/{endpoint}/runsync</code> ou <code>/run</code><br>
          <b style="color:var(--text)">3.</b> A GPU renderiza e devolve a URL do MP4<br>
          <b style="color:var(--text)">4.</b> Custo estimado por GPU-segundo (delay + execução)<br>
          <b style="color:var(--text)">5.</b> Nada de webhook/callback — o dado volta na resposta
        </div>
      </div>
    </div>
    <div class="section-title">Fila de produção <button class="btn small" onclick="loadJobs()">↻ Atualizar</button></div>
    <div class="card"><div id="fab-jobs">…</div></div>`;

  $("#fab-go").onclick = createJob;
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
  $("#fab-health").onclick = async () => {
    $("#fab-health-out").innerHTML = `<small style="color:var(--muted)">Consultando…</small>`;
    const h = await api("/runpod/health");
    $("#fab-health-out").innerHTML = h.ok
      ? `<span class="badge green">workers prontos: ${h.workers.prontos}</span>
         <span class="badge gold">fila: ${h.fila.na_fila}</span>
         <span class="badge violet">executando: ${h.fila.em_execucao}</span>`
      : `<span class="badge red">${esc(h.message || "RunPod indisponível")}</span>`;
  };
  loadRunpodCard();
  loadJobs();
}

async function loadRunpodCard() {
  const el = $("#fab-runpod");
  if (!el) return;
  try {
    const w = await api("/runpod/workflow");
    const st = await api("/status");
    const rp = st.providers.runpod || {};
    el.innerHTML = `
      <div class="kv"><span>Endpoint</span><b>${esc(rp.endpoint_id || "não configurado")}</b></div>
      <div class="kv"><span>Status</span>
        <span class="badge ${rp.conectado ? "green" : "gray"}">${rp.conectado ? "● conectado" : "○ desconectado"}</span></div>
      <div class="kv"><span>Workflow</span><b>${esc(w.fonte)}</b></div>
      <div class="kv"><span>GPU</span><b>US$ ${Number(w.custo_gpu_hora).toFixed(2)}/h</b></div>
      ${rp.conectado ? "" : `<small style="color:var(--gold);display:block;margin-top:8px">
        Configure API key e endpoint id em <span class="link-gold" onclick="location.hash='#/apis'">APIs & Conexões</span>.</small>`}`;
  } catch { el.innerHTML = `<small style="color:var(--faint)">—</small>`; }
}

async function createJob() {
  const product = $("#fab-product").value.trim();
  if (!product) return toast("Informe o produto/tema", true);
  const body = {
    product,
    prompt: $("#fab-prompt").value.trim(),
    style: $("#fab-style").value,
    duration: +$("#fab-dur").value || 6,
    mode: $("#fab-mode").value,
  };
  try {
    const r = await api("/fabrica/jobs", { method: "POST", body });
    const st = r.job.status;
    toast(st === "pronto" ? "Vídeo renderizado ✔"
      : st === "processando" ? "Job na fila do RunPod — use ↻ para acompanhar"
      : st === "erro" ? (r.runpod_configurado ? "RunPod recusou o job" : "Configure o RunPod primeiro")
      : "Job criado");
    loadMe(); loadJobs();
  } catch (e) { toast(e.message, true); }
}
window.createJob = createJob;

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

async function loadJobs() {
  const el = $("#fab-jobs");
  if (!el) return;
  const data = await api("/fabrica/jobs");
  if (!data.jobs.length) {
    el.innerHTML = `<div class="empty">Nenhum job ainda — crie o primeiro vídeo ao lado.
      ${data.runpod_configurado ? "" : "<br>⚠️ RunPod não configurado (aba APIs & Conexões)."}</div>`;
    return;
  }
  el.innerHTML = `<table class="table">
    <thead><tr><th>Job</th><th>Produto</th><th>Estilo</th><th>Status</th><th>Custo</th><th></th></tr></thead>
    <tbody>${data.jobs.map(j => {
      const [ico, lb, cls] = JOB_STATUS[j.status] || ["•", j.status, ""];
      return `<tr>
        <td style="font-family:monospace;font-size:12px">${j.id}<br>
          <small style="color:var(--faint)">${j.mode || "sync"}${j.runpod_job_id ? " · " + String(j.runpod_job_id).slice(0, 12) : ""}</small></td>
        <td><b>${esc(j.product)}</b><br><small style="color:var(--faint)">${j.created_at?.slice(0, 16).replace("T", " ")}</small></td>
        <td><span class="badge gray">${esc(j.style)} · ${j.duration}s</span></td>
        <td><span class="job-status ${cls}">${ico} ${lb}</span>
          ${j.error ? `<br><small style="color:var(--red)">${esc(j.error)}</small>` : ""}
          ${j.media?.file ? `<br><small style="color:var(--green)">💾 ${fmtBytes(j.media.bytes)}</small>` : ""}
          ${j.media_error ? `<br><small style="color:var(--gold)" title="${esc(j.media_error)}">⚠ arquivo não salvo</small>` : ""}
          ${j.execution_ms ? `<br><small style="color:var(--faint)">exec ${(j.execution_ms / 1000).toFixed(1)}s</small>` : ""}</td>
        <td class="num">${j.cost_usd != null ? "$" + Number(j.cost_usd).toFixed(4) : "—"}</td>
        <td style="white-space:nowrap">
          ${j.status === "processando" && j.runpod_job_id
            ? `<button class="btn small" onclick="pollJob('${j.id}')">↻ Consultar</button>` : ""}
          ${j.status === "pronto" && (j.media_url || j.video_url)
            ? `<button class="btn small primary" onclick="playJob(${jattr(j)})">▶ Assistir</button>` : ""}
          ${j.media_url
            ? `<a class="btn small ghost" href="${j.media_url}" target="_blank" rel="noopener">⬇ Abrir</a>` : ""}
          ${j.status === "pronto" && j.media_url
            ? `<button class="btn small" onclick="abrirPublicar(${jattr(j)})">📤 Publicar</button>` : ""}
          ${j.publicacao_id
            ? `<a class="btn small ghost" href="#/publicacoes">📤 Ver publicação</a>` : ""}
          <button class="btn small danger" onclick="delJob('${j.id}')">✕</button>
        </td></tr>`;
    }).join("")}</tbody></table>`;
  if (data.jobs.some(j => ["fila", "enviado", "processando"].includes(j.status))) {
    fabricaTimer = setTimeout(loadJobs, 8000);
  }
}
window.loadJobs = loadJobs;

window.pollJob = async (id) => {
  try {
    const r = await api(`/fabrica/jobs/${id}/poll`);
    toast(`Status: ${r.job.status}`);
    loadJobs();
  } catch (e) { toast(e.message, true); }
};

window.playJob = (job) => {
  // o arquivo salvo no servidor não expira; a URL do worker, sim
  const src = job.media_url || job.video_url;
  const expira = !job.media_url && job.video_url;
  openModal(`
    <h2>${esc(job.product)}</h2>
    <video controls autoplay style="width:100%;border-radius:12px;margin-top:12px;background:#000"
      src="${esc(src)}"></video>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <a class="btn primary" href="${esc(job.media_url ? job.media_url + "?download=true" : job.video_url)}"
         ${job.media_url ? "download" : ""}>⬇ Baixar</a>
      <button class="btn" onclick="copyText(${jattr(src)}, 'Link copiado!')">📋 Copiar link</button>
      ${job.cost_usd != null ? `<span class="badge gold">custo $${Number(job.cost_usd).toFixed(4)}</span>` : ""}
      ${job.media?.bytes ? `<span class="badge green">${fmtBytes(job.media.bytes)} no servidor</span>` : ""}
    </div>
    ${expira ? `<small style="color:var(--gold);display:block;margin-top:8px">
      ⚠ Este job não tem cópia local — o link é do S3 do RunPod e expira.
      ${job.media_error ? esc(job.media_error) : ""}</small>` : ""}`);
};

window.delJob = async (id) => { await api(`/fabrica/jobs/${id}`, { method: "DELETE" }); loadJobs(); };

window.sendToFabrica = (product, prompt) => {
  sessionStorage.setItem("fabrica-prefill", JSON.stringify({ product, prompt }));
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
        <td style="color:var(--muted)">${i.saved_at?.slice(0, 10)}
          ${i.payload?.bytes ? `<br><small style="color:var(--faint)">${fmtBytes(i.payload.bytes)}</small>` : ""}</td>
        <td style="white-space:nowrap">
          ${i.payload?.url ? `<a class="btn small primary" href="${i.payload.url}" target="_blank" rel="noopener">▶ Abrir</a>` : ""}
          <button class="btn small danger" onclick="removeLib('${i.id}')">Remover</button></td>
      </tr>`).join("")}</tbody></table>`;
}
window.removeLib = async (id) => {
  await api(`/library/${id}`, { method: "DELETE" });
  toast("Item removido"); viewBiblioteca();
};

// ============================================================ OUTLIERS
async function viewOutliers() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Outliers 🚀</h1>
      <p>O sinal que a plataforma nativa não mostra: vídeos que estão performando
      muito acima do normal do próprio criador — ou seja, o que está viralizando
      <b>antes</b> de aparecer na aba de tendências.</p>
    </div></div>
    <div class="card">
      <div class="form-row">
        <div class="grow"><input id="out-q" placeholder="ex: skincare, garrafa térmica, nicho dark…" value="achadinhos de casa" /></div>
        <select id="out-pf" style="width:150px"><option value="all">Todas as redes</option>
          <option value="tiktok">TikTok</option><option value="instagram">Instagram</option>
          <option value="youtube">YouTube</option></select>
        <select id="out-period" style="width:130px"><option value="24h">24h</option>
          <option value="7d">7 dias</option><option value="30d" selected>30 dias</option>
          <option value="90d">90 dias</option></select>
        <select id="out-min" style="width:170px"><option value="30">Score ≥ 30</option>
          <option value="50">Score ≥ 50 (forte)</option><option value="70">Score ≥ 70 (extremo)</option></select>
        <button class="btn primary" id="out-go">🚀 Detectar outliers</button>
      </div>
      <small style="color:var(--faint);display:block;margin-top:8px">
        Baseline = mediana de views do criador no corpus pesquisado; sem histórico,
        usamos a mediana do nicho (honesto: nunca o próprio vídeo).</small>
    </div>
    <div id="out-summary" style="margin-top:14px"></div>
    <div id="out-results" style="margin-top:14px">${skeletonGrid(4, 120)}</div>`;

  $("#out-go").onclick = runOutliers;
  $("#out-q").addEventListener("keydown", e => { if (e.key === "Enter") runOutliers(); });
  runOutliers();
}

async function runOutliers() {
  const params = new URLSearchParams({
    q: $("#out-q").value.trim() || "tendências",
    platform: $("#out-pf").value, period: $("#out-period").value,
    min_score: $("#out-min").value, limit: "14",
  });
  $("#out-results").innerHTML = skeletonGrid(4, 120);
  const d = await api("/outliers?" + params);
  loadMe();

  const dest = d.destaque;
  $("#out-summary").innerHTML = `
    <div class="grid cols-4">
      ${kpi("Vídeos no corpus", fmtNum(d.corpus.videos), "usados para calcular o baseline")}
      ${kpi("Mediana do nicho", fmtNum(d.corpus.mediana_views) + " views", "o “normal” desta pesquisa")}
      ${kpi("Outliers encontrados", d.total, d.criterio, "var(--violet)")}
      ${kpi("Melhor outlier", dest ? `${dest.ratio}x` : "—",
        dest ? `${dest.handle} · score ${dest.score}` : "nenhum acima do corte", "var(--green)")}
    </div>`;

  if (!d.outliers.length) {
    $("#out-results").innerHTML = `<div class="empty">Nenhum outlier acima do corte.
      Tente baixar o score mínimo ou pesquisar outro tema.</div>`;
    return;
  }

  $("#out-results").innerHTML = `<div class="card"><h3>Vídeos furando a curva</h3>
    <table class="table"><thead><tr>
      <th>#</th><th>Vídeo</th><th>Rede</th><th class="num">Views</th>
      <th class="num">Baseline</th><th class="num">Ratio</th><th>Outlier</th><th></th>
    </tr></thead><tbody>
    ${d.outliers.map((v, i) => `
      <tr>
        <td class="num" style="color:var(--faint)">${i + 1}</td>
        <td style="max-width:340px"><b>${esc(v.title || "—")}</b><br>
          <small style="color:var(--muted)">${esc(v.handle || v.author)} · ${timeAgoH(v.age_hours)}
          <span class="src-badge src-${v.source}">${v.source}</span></small></td>
        <td>${pfBadge(v.platform)}</td>
        <td class="num">${fmtNum(v.views)}</td>
        <td class="num" style="color:var(--muted)">${fmtNum(v.creator_baseline)}</td>
        <td class="num"><b style="color:var(--gold)">${v.outlier_ratio}x</b></td>
        <td style="min-width:130px">
          <div style="display:flex;align-items:center;gap:8px">
            <div class="score-bar" style="flex:1"><i style="width:${v.outlier_score}%"></i></div>
            <b>${v.outlier_score}</b>
          </div>
          <small style="color:var(--faint)">${v.tier?.label || ""}</small></td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick='saveToLibrary("video", ${jattr(v.uid)}, ${jattr(v.title)}, ${jattr(v)})'>📁</button>
          <button class="btn small ghost" onclick='goToLab(${jattr(v.title)})'>🧪</button>
          ${v.url ? `<a class="btn small ghost" href="${esc(v.url)}" target="_blank" rel="noopener">↗</a>` : ""}
        </td>
      </tr>`).join("")}
    </tbody></table></div>`;
}

// ============================================================ RESEARCH AGENTS
const AGENT_OBJ = {
  hooks: "Hooks que funcionam", formato: "Formato vencedor",
  produto: "Produto em alta", criador: "Criadores furando a curva",
};

async function viewAgents() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Research Agents 🤖</h1>
      <p>Descreva o que você quer saber e escolha a frequência. O agente roda a
      pesquisa completa — busca, outlier detection, facetas e recomendação de
      formato — e entrega o dossiê pronto no seu Slack, Discord ou webhook.</p>
    </div></div>
    <div class="grid cols-2">
      <div class="card">
        <h3>Novo agente</h3>
        <div class="field"><label>O que pesquisar</label>
          <input id="ag-q" placeholder="ex: quais hooks funcionam em skincare no TikTok" /></div>
        <div class="form-row" style="margin-top:8px">
          <select id="ag-pf" style="flex:1"><option value="all">Todas as redes</option>
            <option value="tiktok">TikTok</option><option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option></select>
          <select id="ag-obj" style="flex:1">
            ${Object.entries(AGENT_OBJ).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
          </select>
          <select id="ag-sched" style="flex:1">
            <option value="manual">Manual</option><option value="daily">Diário</option>
            <option value="weekly">Semanal</option></select>
        </div>
        <div class="field" style="margin-top:8px"><label>Webhook / Slack / Discord (opcional)</label>
          <input id="ag-hook" placeholder="https://hooks.slack.com/services/…" /></div>
        <button class="btn primary" id="ag-create" style="margin-top:10px">🤖 Criar agente</button>
        <small style="color:var(--faint);display:block;margin-top:8px">
          Cada execução custa <b>100 créditos</b> (o mesmo preço do concorrente).</small>
      </div>
      <div class="card"><h3>Como o dossiê chega</h3>
        <div class="kv"><span>Corpus analisado</span><b>~18–54 vídeos por execução</b></div>
        <div class="kv"><span>Outliers</span><b>top 8 com baseline e ratio</b></div>
        <div class="kv"><span>Facetas</span><b>hashtags, sons e criadores</b></div>
        <div class="kv"><span>Recomendações</span><b>o que replicar e por quê</b></div>
        <div class="kv"><span>Hooks</span><b>5 hooks gerados pelo Estúdio IA</b></div>
        <div class="kv"><span>Entrega</span><b>webhook · Slack · Discord</b></div>
        <small style="color:var(--faint);display:block;margin-top:10px">
          O agendador roda no próprio servidor (loop asyncio) — sem Celery, sem
          infraestrutura extra.</small>
      </div>
    </div>
    <div class="section-title">Seus agentes</div>
    <div class="card" id="agents-list">…</div>`;

  $("#ag-create").onclick = async () => {
    const q = $("#ag-q").value.trim();
    if (!q) return toast("Descreva o que o agente deve pesquisar", true);
    const hook = $("#ag-hook").value.trim();
    const body = {
      name: q.slice(0, 60), query: q, platform: $("#ag-pf").value,
      objective: $("#ag-obj").value, schedule: $("#ag-sched").value,
      webhook: hook.startsWith("http") && !/slack|discord/.test(hook) ? hook : "",
      slack: /slack/.test(hook) ? hook : "",
      discord: /discord/.test(hook) ? hook : "",
    };
    try {
      await api("/agents", { method: "POST", body });
      toast("Agente criado 🤖");
      viewAgents();
    } catch (e) { toast(e.message, true); }
  };
  loadAgents();
}

async function loadAgents() {
  const d = await api("/agents");
  const st = d.stats;
  if (!d.agents.length) {
    $("#agents-list").innerHTML = `<div class="empty">Nenhum agente ainda.
      Crie o primeiro acima: ele pesquisa por você todos os dias.</div>`;
    return;
  }
  $("#agents-list").innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
      <span class="badge gold">${st.agentes} agentes</span>
      <span class="badge green">${st.ativos} ativos</span>
      <span class="badge violet">${st.execucoes} execuções</span>
      ${st.proxima_execucao ? `<span class="badge gray">próxima: ${st.proxima_execucao.replace("T", " ").replace("Z", "")}</span>` : ""}
    </div>
    ${d.agents.map(a => `
      <div class="agent-row">
        <div>
          <b>${esc(a.name)}</b> <span class="badge ${a.schedule === "manual" ? "gray" : "cyan"}">${a.schedule}</span>
          <br><small style="color:var(--muted)">${esc(a.query)} · ${AGENT_OBJ[a.objective] || a.objective}
          · ${PF_META[a.platform]?.label || "todas as redes"}</small>
          <br><small style="color:var(--faint)">
          ${a.last_report ? `último dossiê: ${a.last_report.at} · ${a.last_report.outliers} outliers de ${a.last_report.videos} vídeos` : "nunca executado"}
          ${a.next_run ? ` · próxima: ${a.next_run.replace("T", " ").replace("Z", "")}` : ""}</small>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
          <button class="btn small primary" onclick="runAgentNow('${a.id}')">▶ Executar (100 cr)</button>
          <button class="btn small" onclick="openAgentReport('${a.id}')">📄 Dossiê</button>
          <button class="btn small ghost" onclick="deleteAgent('${a.id}')">🗑</button>
        </div>
      </div>`).join("")}`;
}

window.runAgentNow = async (id) => {
  toast("Executando agente… isso leva alguns segundos");
  try {
    const d = await api(`/agents/${id}/run`, { method: "POST" });
    loadMe();
    toast(`Dossiê pronto: ${d.run.report.outliers.length} outliers`);
    openReportModal(d.run.report);
    loadAgents();
  } catch (e) { toast(e.message, true); }
};

window.deleteAgent = async (id) => {
  if (!confirm("Excluir este agente?")) return;
  await api(`/agents/${id}`, { method: "DELETE" });
  toast("Agente removido");
  loadAgents();
};

window.openAgentReport = async (id) => {
  const d = await api(`/agents/${id}`);
  const run = (d.agent.runs || [])[0];
  if (!run) return toast("Este agente ainda não foi executado", true);
  openReportModal(run.report);
};

function openReportModal(r) {
  openModal(`
    <h2>📄 Dossiê — ${esc(r.query)}</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0">
      <span class="badge gold">${r.objective_label}</span>
      <span class="badge gray">${r.corpus.videos} vídeos</span>
      <span class="badge violet">mediana ${fmtNum(r.corpus.mediana_views)} views</span>
      <span class="badge green">${r.outliers.length} outliers</span>
      <span class="badge cyan">${r.generated_at}</span>
    </div>
    <h3 style="margin-top:14px">O que fazer agora</h3>
    ${r.recomendacoes.map(rec => `
      <div class="report-rec">
        <b>#${rec.prioridade} ${esc(rec.acao)}</b>
        <div class="why">${esc(rec.porque)}</div>
        <div class="why" style="margin-top:2px">${esc(rec.como)}</div>
      </div>`).join("")}
    <h3>Outliers do período</h3>
    <table class="table"><tbody>
      ${r.outliers.map(v => `<tr>
        <td><b>${esc(v.title || "—")}</b><br><small style="color:var(--muted)">${esc(v.handle)}</small></td>
        <td class="num">${fmtNum(v.views)}</td>
        <td class="num" style="color:var(--gold)">${v.outlier_ratio}x</td>
        <td class="num">${v.outlier_score}</td>
      </tr>`).join("") || `<tr><td>Nenhum outlier acima do corte nesta execução.</td></tr>`}
    </tbody></table>
    ${r.hooks_sugeridos?.length ? `<h3>Hooks sugeridos</h3>
      <div class="tags-row" style="flex-wrap:wrap">${r.hooks_sugeridos.map(h =>
        `<span class="chip">${esc(typeof h === "string" ? h : h.text || h.hook || "")}</span>`).join("")}</div>` : ""}
    ${r.facetas?.top_hashtags?.length ? `<h3>Hashtags dominantes</h3>
      <div class="tags-row" style="flex-wrap:wrap">${r.facetas.top_hashtags.slice(0, 8).map(t =>
        `<span class="mini-tag">${esc(t.tag)} · ${fmtNum(t.reach)}</span>`).join("")}</div>` : ""}
  `);
}

// ============================================================ USO & PLANO
async function viewBilling() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Uso & Plano 💳</h1>
      <p>Créditos, cotas diárias, chaves de API e custo por ação — a mesma mecânica
      dos apps de referência (Virlo, Kalodata, ViralFindr), agora transparente.</p>
    </div></div>
    <div id="bill-me"></div>
    <div class="section-title">Planos</div>
    <div class="plan-grid" id="bill-plans"></div>
    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><h3>Consumo por ação (14 dias)</h3><div id="bill-usage">…</div></div>
      <div class="card"><h3>Chaves de API</h3><div id="bill-keys">…</div>
        <div class="form-row" style="margin-top:10px">
          <div class="grow"><input id="key-label" placeholder="nome da chave (ex: integração externa)" /></div>
          <button class="btn primary small" id="key-new">+ Gerar chave</button>
        </div>
        <small style="color:var(--faint);display:block;margin-top:8px">
          Use no header <code>X-API-Key</code>. A chave completa aparece uma única vez.</small>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><h3>Tabela de preços em créditos</h3><div id="bill-costs">…</div></div>`;

  const [me, usage, plans] = await Promise.all([
    api("/me"), api("/billing/usage?days=14"), api("/billing/plans"),
  ]);
  state.me = me;
  const p = me.plano;

  $("#bill-me").innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
        <div>
          <h3 style="margin:0">Plano ${p.plan_name} <span class="badge gold">${p.plan === "free" ? "grátis" : "R$ " + p.price_brl + "/mês"}</span></h3>
          <small style="color:var(--muted)">workspace ${esc(me.tenant.name)} · ciclo ${p.cycle_start}
          · ${p.seats} assento(s) · histórico ${p.history_days} dias</small>
        </div>
        <div style="text-align:right">
          <div style="font-size:28px;font-weight:800;color:var(--gold)">${fmtNum(p.credits_remaining)}</div>
          <small style="color:var(--muted)">de ${fmtNum(p.credits_total)} créditos restantes</small>
        </div>
      </div>
      <div class="gauge ${p.credits_pct >= 85 ? "warn" : ""}"><i style="width:${100 - p.credits_pct}%"></i></div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px">
        <small style="color:var(--muted)">${p.credits_used} créditos usados neste ciclo</small>
        <small style="color:var(--muted)">${p.daily_used}/${p.daily_limit} consultas hoje</small>
        <small style="color:var(--muted)">${me.agents.agentes} agentes · ${me.agents.execucoes} execuções</small>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
        <button class="btn small" onclick="topUp(500)">+500 créditos</button>
        <button class="btn small" onclick="topUp(2000)">+2.000 créditos</button>
        <button class="btn small ghost" onclick="topUp(10000)">+10.000 créditos</button>
      </div>
    </div>`;

  $("#bill-plans").innerHTML = plans.plans.map(pl => `
    <div class="card plan-card ${pl.id === p.plan ? "current" : ""}">
      ${pl.id === p.plan ? '<span class="badge gold tag-current">atual</span>' : ""}
      <b>${pl.name}</b>
      <div class="price">${pl.price_brl === null ? "custom" : pl.price_brl === 0 ? "R$ 0" : "R$ " + pl.price_brl}</div>
      <small style="color:var(--muted)">${fmtNum(pl.credits)} créditos/mês · ${pl.daily_queries} consultas/dia</small>
      <ul>${pl.features.map(f => `<li>${f}</li>`).join("")}</ul>
      ${pl.id === p.plan ? "" : `<button class="btn small primary" onclick="changePlan('${pl.id}')">Mudar para ${pl.name}</button>`}
    </div>`).join("");

  $("#bill-usage").innerHTML = `
    <div style="margin-bottom:10px">${areaChart(usage.serie_diaria.map(s => s.credits), "#f0b429", 80)}</div>
    <table class="table"><thead><tr><th>Ação</th><th class="num">Chamadas</th><th class="num">Créditos</th></tr></thead>
      <tbody>${usage.por_acao.map(a => `<tr>
        <td>${a.action}</td><td class="num">${a.calls}</td><td class="num">${a.credits}</td>
      </tr>`).join("") || '<tr><td colspan="3" style="color:var(--muted)">Nenhum consumo no período.</td></tr>'}
      </tbody></table>`;

  $("#bill-keys").innerHTML = `<table class="table"><tbody>
    ${me.chaves.map(k => `<tr>
      <td><b>${esc(k.label)}</b><br><small class="code-line" style="border:0;background:none;padding:0">${esc(k.masked)}</small></td>
      <td class="num"><small style="color:var(--muted)">${k.last_used || "nunca usada"}</small></td>
      <td><button class="btn small ghost" onclick="revokeKey('${k.id}')">revogar</button></td>
    </tr>`).join("")}
    </tbody></table>`;

  const skip = new Set(["ingest"]);
  $("#bill-costs").innerHTML = `<div class="tags-row" style="flex-wrap:wrap">
    ${Object.entries(plans.custo_por_acao).filter(([k]) => !skip.has(k)).map(([k, v]) =>
      `<span class="chip">${k} <b style="color:var(--gold)">${v}</b></span>`).join("")}
    <span class="chip">ingest <b style="color:var(--green)">grátis</b></span></div>`;

  $("#key-new").onclick = async () => {
    const label = $("#key-label").value.trim() || "nova chave";
    const d = await api("/billing/keys", { method: "POST", body: { label } });
    openModal(`<h2>🔑 Chave criada</h2>
      <p style="color:var(--muted);font-size:13px">${esc(d.aviso)}</p>
      <div class="code-line" id="new-key">${esc(d.key.key)}</div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button class="btn primary small" onclick="copyText('${esc(d.key.key)}', 'Chave copiada')">📋 Copiar</button>
        <button class="btn small" onclick="useKey('${esc(d.key.key)}')">Usar nesta sessão</button>
      </div>`);
    viewBilling();
  };
}

window.useKey = (key) => {
  localStorage.setItem("mineraai_api_key", key);
  toast("Chave ativa nesta sessão");
  closeModal();
  loadMe();
};

window.changePlan = async (plan) => {
  try {
    const d = await api("/billing/plan", { method: "POST", body: { plan } });
    toast(`Plano alterado para ${d.plano.plan_name}`);
    loadMe();
    viewBilling();
  } catch (e) { toast(e.message, true); }
};

window.topUp = async (amount) => {
  try {
    await api("/billing/credits", { method: "POST", body: { amount, reason: "top-up pela UI" } });
    toast(`+${fmtNum(amount)} créditos adicionados`);
    loadMe();
    viewBilling();
  } catch (e) { toast(e.message, true); }
};

window.revokeKey = async (id) => {
  if (!confirm("Revogar esta chave? Integrações que a usam param de funcionar.")) return;
  await api(`/billing/keys/${id}`, { method: "DELETE" });
  toast("Chave revogada");
  viewBilling();
};

// ============================================================ LOJAS
async function viewLojas() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Lojas 🏪</h1>
      <p>Quem está faturando no TikTok Shop: catálogo, GMV estimado, crescimento,
      dependência de live commerce e quantos criadores sustentam a operação.</p>
    </div></div>
    <div class="card"><div class="form-row">
      <div class="grow"><input id="shop-q" placeholder="buscar loja ou categoria…" value="" /></div>
      <select id="shop-cat" style="width:180px"><option value="">Todas as categorias</option></select>
      <select id="shop-sort" style="width:190px">
        <option value="gmv">GMV estimado</option><option value="growth">Crescimento</option>
        <option value="units">Unidades</option><option value="creators">Criadores afiliados</option>
        <option value="products">Catálogo</option></select>
      <button class="btn primary" id="shop-go">🔎 Buscar</button>
    </div></div>
    <div id="shop-results" style="margin-top:14px">${skeletonGrid(3, 120)}</div>`;

  $("#shop-go").onclick = loadShops;
  $("#shop-q").addEventListener("keydown", e => { if (e.key === "Enter") loadShops(); });
  loadShops();
}

async function loadShops() {
  const cat = $("#shop-cat").value;
  const q = $("#shop-q").value.trim();
  const params = new URLSearchParams({ sort: $("#shop-sort").value, limit: "16" });
  if (q) params.set("q", q);
  if (cat) params.set("category", cat);
  const d = await api("/shops?" + params);
  loadMe();
  if ($("#shop-cat").options.length <= 1) {
    $("#shop-cat").innerHTML += d.categorias.map(c => `<option value="${c}">${c}</option>`).join("");
  }
  $("#shop-results").innerHTML = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0">${d.shops.length} lojas no ranking</h3>
      <span class="badge gold">GMV total ${fmtBRL(d.total_gmv)}</span>
    </div>
    <table class="table"><thead><tr><th>#</th><th>Loja</th><th class="num">GMV est.</th>
      <th class="num">Cresc.</th><th class="num">Catálogo</th><th class="num">Criadores</th>
      <th class="num">Live share</th><th>Curva</th></tr></thead><tbody>
    ${d.shops.map((s, i) => `<tr>
      <td class="num" style="color:var(--faint)">${i + 1}</td>
      <td><b>${esc(s.name)}</b> ${s.verified ? "✓" : ""}<br>
        <small style="color:var(--muted)">${s.category} · ${s.rating}★</small></td>
      <td class="num">${fmtBRL(s.gmv)}<br><small style="color:var(--faint)">${fmtBRL(s.gmv_range?.gmv_low || 0)}–${fmtBRL(s.gmv_range?.gmv_high || 0)}</small></td>
      <td>${s.growth >= 0 ? `<span class="pos">▲ ${s.growth}%</span>` : `<span class="neg">▼ ${Math.abs(s.growth)}%</span>`}</td>
      <td class="num">${s.products}</td>
      <td class="num">${fmtNum(s.creators_affiliated)}</td>
      <td class="num">${s.live_share}%</td>
      <td>${sparkline(s.curve)}</td>
    </tr>`).join("")}
    </tbody></table>
    <small style="color:var(--faint);display:block;margin-top:8px">${d.note}</small></div>`;
}

// ============================================================ APIS & CONEXÕES
const GRUPOS = {
  plataformas: { titulo: "Plataformas oficiais", desc: "APIs oficiais das redes — dado primário." },
  dados:       { titulo: "Dados pagos", desc: "Fonte de cobertura real sob demanda." },
  ia:          { titulo: "Inteligência artificial", desc: "Cada provedor com a sua própria chave." },
  fontes:      { titulo: "Fontes gratuitas", desc: "Uma credencial por fonte — nunca compartilhada." },
  producao:    { titulo: "Produção de vídeo", desc: "RunPod serverless chamado direto pelo MineraAI." },
};

const EXTRA_ACOES = {
  reddit: `<button class="btn small ghost" onclick="redditToken()">🔑 Emitir token OAuth</button>`,
  mercadolivre: `<button class="btn small ghost" onclick="meliAuthorize()">🔗 Autorizar (OAuth)</button>
                 <button class="btn small ghost" onclick="meliRefresh()">↻ Renovar token</button>`,
  virlo: `<button class="btn small ghost" onclick="virloSaldo()">💰 Ver saldo</button>`,
  youtube_canal: `<button class="btn small ghost" onclick="ytAuthorize()">🔗 Autorizar</button>
                  <button class="btn small ghost" onclick="ytRefresh()">↻ Renovar</button>
                  <button class="btn small ghost" onclick="ytCanal()">📺 Canal</button>`,
  runpod: `<button class="btn small ghost" onclick="runpodHealth()">🩺 Health</button>`,
};

async function viewApis() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>APIs & Conexões 🔌</h1>
      <p>Uma integração por card, com credencial, teste e custo próprios.
      Nada é compartilhado entre fontes: se uma cair, as outras continuam.</p>
    </div></div>
    <div id="api-tokens" class="card" style="display:none"></div>
    <div id="api-body"><div class="empty">Carregando integrações…</div></div>`;

  let inv;
  try {
    inv = await api("/integrations");
  } catch (e) {
    $("#api-body").innerHTML = `<div class="empty">Erro ao carregar: ${esc(e.message)}</div>`;
    return;
  }
  const cfg = await api("/settings");

  const porGrupo = {};
  inv.integracoes.filter(i => i.id !== "ia").forEach(i => {
    (porGrupo[i.grupo] ||= []).push(i);
  });

  $("#api-body").innerHTML = Object.entries(GRUPOS).map(([g, meta]) => {
    const itens = porGrupo[g] || [];
    if (!itens.length) return "";
    return `<div class="section-title">${meta.titulo} <small style="color:var(--faint);font-weight:500">— ${meta.desc}</small></div>
      <div class="grid cols-2">${itens.map(i => cardIntegracao(i, cfg)).join("")}</div>`;
  }).join("");

  if (inv.meli_tokens?.access) {
    $("#api-tokens").style.display = "block";
    $("#api-tokens").innerHTML = `<h3>Mercado Livre — tokens ativos</h3>
      <div class="kv"><span>Access token</span><b>${esc(inv.meli_tokens.access)}</b></div>
      <div class="kv"><span>Refresh token</span><b>${esc(inv.meli_tokens.refresh)}</b></div>
      <div class="kv"><span>Expira em (epoch)</span><b>${esc(inv.meli_tokens.expira_em || "—")}</b></div>
      <small style="color:var(--muted)">O token é renovado automaticamente quando faltam 5 minutos.
      Redirect URI esperado: <code>${esc(inv.meli_redirect_uri)}</code></small>`;
  }
}

function cardIntegracao(i, cfg) {
  const campos = i.campos || [];
  const campoHtml = campos.map(c => {
    const valor = cfg.settings[c.k] ?? "";
    if (c.tipo === "bool") {
      return `<label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer;margin:8px 0">
        <input type="checkbox" id="set-${c.k}" style="width:auto" ${valor === "1" ? "checked" : ""} /> ${c.label}</label>`;
    }
    if (c.tipo === "textarea") {
      return `<div class="field" style="margin-bottom:8px"><label>${c.label}</label>
        <textarea id="set-${c.k}" rows="3" placeholder="cole o JSON exportado do ComfyUI (Save → API)">${esc(valor)}</textarea></div>`;
    }
    return `<div class="field" style="margin-bottom:8px"><label>${c.label}</label>
      <input type="${c.tipo === "secret" ? "password" : "text"}" id="set-${c.k}"
        placeholder="${valor ? "••• " + esc(valor) + " (salvo)" : "colar aqui…"}" /></div>`;
  }).join("");

  const chaveDeTeste = { suggest: "suggest", google_suggest: "suggest" }[i.id] || i.id;
  return `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <h3 style="margin:0">${esc(i.oficial)}</h3>
      <span class="badge ${i.conectado ? "green" : "gray"}">${i.conectado ? "● conectado" : "○ não conectado"}</span>
    </div>
    <small style="color:var(--muted)">${esc(i.custo)}</small>
    <div style="margin-top:12px">${campoHtml || '<small style="color:var(--faint)">Nenhum campo necessário — já funciona.</small>'}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      ${campos.length ? `<button class="btn primary small" onclick="saveProvider('${i.id}', ${jattr(campos.map(c => c.k))})">💾 Salvar</button>` : ""}
      <button class="btn small" onclick="testProvider('${chaveDeTeste}', '${i.id}')">🔍 Testar</button>
      ${EXTRA_ACOES[i.id] || ""}
    </div>
    <div id="test-${i.id}" style="margin-top:8px"></div>
  </div>`;
}

window.saveProvider = async (kind, fields) => {
  const patch = {};
  fields.forEach(f => {
    const el = $(`#set-${f}`);
    if (!el) return;
    if (el.type === "checkbox") { patch[f] = el.checked ? "1" : "0"; return; }
    const v = el.value?.trim();
    if (v) patch[f] = v;
  });
  if (!Object.keys(patch).length) return toast("Preencha ao menos um campo", true);
  await api("/settings", { method: "POST", body: { settings: patch } });
  toast("Configurações salvas ✔");
  loadStatus(); viewApis();
};

window.testProvider = async (servico, ancoragem) => {
  const alvo = $(`#test-${ancoragem || servico}`);
  if (alvo) alvo.innerHTML = `<span class="badge gray">testando…</span>`;
  try {
    const r = await api(`/settings/test/${servico}`, { method: "POST" });
    if (alvo) alvo.innerHTML = `<span class="badge ${r.ok ? "green" : "red"}">${esc(r.message)}</span>`;
  } catch (e) {
    if (alvo) alvo.innerHTML = `<span class="badge red">${esc(e.message)}</span>`;
  }
};

window.redditToken = async () => {
  const r = await api("/integrations/reddit/token", { method: "POST" });
  toast(r.message, !r.ok);
  viewApis();
};

window.meliAuthorize = async () => {
  const r = await api("/integrations/meli/authorize");
  if (!r.ok) return toast(r.message, true);
  window.open(r.url, "_blank", "noopener");
  openModal(`<h2>🔗 Autorizar Mercado Livre</h2>
    <p style="color:var(--muted);font-size:13px">Autorize na aba que abriu: ao voltar,
    o servidor troca o código pelos tokens sozinho e a lista de cards se atualiza.
    <br><br><b>Se a aba não voltar para este servidor</b> (redirect apontando para
    outro domínio), copie o <code>code</code> da URL e cole abaixo.</p>
    <div class="code-line">redirect_uri: ${esc(r.redirect_uri)}</div>
    <div class="field" style="margin-top:12px"><label>Código (code) — opcional</label>
      <input id="meli-code" placeholder="TG-xxxxxxxx" /></div>
    <button class="btn primary" onclick="meliExchange()">Concluir com o código</button>
    <button class="btn ghost" onclick="closeModal(); viewApis()">Já autorizei — atualizar</button>`);
};

window.meliExchange = async () => {
  const code = $("#meli-code").value.trim();
  if (!code) return toast("Cole o code", true);
  try {
    const r = await api("/integrations/meli/callback", { method: "POST", body: { code } });
    toast(r.message || (r.ok ? "Autorizado" : "Falhou"), !r.ok);
    if (r.ok) { closeModal(); viewApis(); }
  } catch (e) { toast(e.message, true); }
};

window.meliRefresh = async () => {
  const r = await api("/integrations/meli/refresh", { method: "POST" });
  toast(r.message || (r.ok ? "Token renovado" : "Falhou"), !r.ok);
  viewApis();
};

window.virloSaldo = async () => {
  const r = await api("/virlo/balance");
  if (!r.ok) return toast(r.message || "Virlo não configurada", true);
  openModal(`<h2>💰 Virlo — conta</h2>
    <div class="code-line" style="white-space:pre-wrap">${esc(JSON.stringify(r.balance, null, 2))}</div>
    <small style="color:var(--muted);display:block;margin-top:10px">
      Orbit/Satellite/Comet custam US$ 0,50 cada (≈60 créditos). Leitura é gratuita.</small>`);
};

window.ytAuthorize = async () => {
  const r = await api("/integrations/youtube/authorize");
  if (!r.ok) return toast(r.message, true);
  window.open(r.url, "_blank", "noopener");
  openModal(`<h2>🔗 Autorizar canal do YouTube</h2>
    <p style="color:var(--muted);font-size:13px">Autorize na aba que abriu, escolhendo o
    canal que vai publicar. Ao voltar, o servidor troca o código pelos tokens sozinho.</p>
    <div class="code-line">redirect_uri: ${esc(r.redirect_uri)}</div>
    <small style="color:var(--faint);display:block;margin-top:10px">
      Escopos pedidos: upload de vídeo + leitura do canal. O Google só devolve
      refresh token com <code>access_type=offline</code> — está no pedido.</small>
    <button class="btn ghost" style="margin-top:10px"
      onclick="closeModal(); viewApis()">Já autorizei — atualizar</button>`);
};

window.ytRefresh = async () => {
  const r = await api("/integrations/youtube/refresh", { method: "POST" });
  toast(r.message || (r.ok ? "Token renovado" : "Falhou"), !r.ok);
  viewApis();
};

window.ytCanal = async () => {
  const r = await api("/integrations/youtube/canal");
  if (!r.ok) return toast(r.message || "Canal não autorizado", true);
  const c = r.canal;
  openModal(`<h2>📺 ${esc(c.titulo)}</h2>
    <div class="kv"><span>Channel ID</span><b>${esc(c.id)}</b></div>
    <div class="kv"><span>Inscritos</span><b>${fmtNum(c.inscritos)}</b></div>
    <div class="kv"><span>Vídeos</span><b>${fmtNum(c.videos)}</b></div>
    <div class="kv"><span>Views totais</span><b>${fmtNum(c.views)}</b></div>`);
};

window.runpodHealth = async () => {
  const r = await api("/runpod/health");
  if (!r.ok) return toast(r.message || "RunPod indisponível", true);
  openModal(`<h2>🩺 RunPod — endpoint</h2>
    <div class="kv"><span>Workers prontos</span><b>${r.workers.prontos}</b></div>
    <div class="kv"><span>Workers executando</span><b>${r.workers.executando}</b></div>
    <div class="kv"><span>Na fila</span><b>${r.fila.na_fila}</b></div>
    <div class="kv"><span>Em execução</span><b>${r.fila.em_execucao}</b></div>`);
};

// ============================================================ PUBLICAÇÕES
window.abrirPublicar = (job) => {
  const titulo = (job.product || "Novo vídeo").slice(0, 100);
  openModal(`<h2>📤 Publicar no YouTube</h2>
    <p style="color:var(--muted);font-size:13px">O vídeo sobe pela conta do canal
    autorizado em <b>APIs &amp; Conexões → Canal do YouTube</b>. O padrão é
    <b>não listado</b> — tornar público é escolha explícita.</p>
    <div class="field"><label>Título</label>
      <input id="pub-titulo" maxlength="100" value="${esc(titulo)}" /></div>
    <div class="field"><label>Descrição</label>
      <textarea id="pub-desc" rows="3">${esc(job.prompt || "")}</textarea></div>
    <div class="form-row">
      <div class="field grow"><label>Tags (separadas por vírgula)</label>
        <input id="pub-tags" placeholder="garrafa térmica, achadinhos" /></div>
      <div class="field" style="width:160px"><label>Privacidade</label>
        <select id="pub-priv">
          <option value="unlisted" selected>Não listado</option>
          <option value="private">Privado</option>
          <option value="public">Público</option>
        </select></div>
    </div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin:10px 0;cursor:pointer">
      <input type="checkbox" id="pub-kids" style="width:auto" /> Conteúdo feito para crianças
    </label>
    <div id="pub-msg"></div>
    <button class="btn primary" id="pub-go" style="margin-top:10px">📤 Publicar agora</button>
    <small style="color:var(--faint);display:block;margin-top:8px">
      Custo: 40 créditos · 1 upload ≈ 1.600 das 10.000 unidades diárias do YouTube.</small>`);
  $("#pub-go").onclick = () => publicarJob(job.id);
};

window.publicarJob = async (jobId) => {
  const titulo = $("#pub-titulo").value.trim();
  if (titulo.length < 3) return toast("Título muito curto", true);
  const tags = $("#pub-tags").value.split(",").map(t => t.trim()).filter(Boolean);
  $("#pub-msg").innerHTML = `<span class="badge gray">enviando para o YouTube…</span>`;
  $("#pub-go").disabled = true;
  try {
    const r = await api(`/fabrica/jobs/${jobId}/publicar`, { method: "POST", body: {
      titulo, descricao: $("#pub-desc").value.trim(), tags,
      privacidade: $("#pub-priv").value, made_for_kids: $("#pub-kids").checked } });
    loadMe();
    openModal(`<h2>✅ Publicado</h2>
      <p style="color:var(--muted);font-size:13px">${esc(r.publicacao.titulo)}</p>
      <div class="code-line">${esc(r.publicacao.url)}</div>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
        <a class="btn primary" href="${esc(r.publicacao.url)}" target="_blank" rel="noopener">▶ Abrir no YouTube</a>
        <button class="btn" onclick="closeModal(); location.hash='#/publicacoes'; viewPublicacoes()">📤 Ver publicações</button>
      </div>
      <small style="color:var(--faint);display:block;margin-top:10px">
        A partir de agora o desempenho deste vídeo entra no corpus da mineração —
        é isso que realimenta o baseline de outlier.</small>`);
    loadJobs();
  } catch (e) {
    $("#pub-msg").innerHTML = `<span class="badge red">${esc(e.message)}</span>`;
    $("#pub-go").disabled = false;
  }
};

async function viewPublicacoes() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Publicações 📤</h1>
      <p>O que saiu da Fábrica e foi ao ar. O desempenho real de cada vídeo volta
      para o corpus da mineração — o loop fecha aqui.</p>
    </div>
    <button class="btn primary" onclick="syncPublicacoes()">↻ Atualizar métricas</button></div>
    <div id="pub-resumo" class="grid cols-4" style="margin-bottom:14px"></div>
    <div id="pub-list"><div class="empty">Carregando…</div></div>`;

  let d;
  try { d = await api("/publicacoes"); }
  catch (e) { $("#pub-list").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const canal = d.canal || {};
  if (!d.autorizado) {
    $("#pub-list").innerHTML = `<div class="empty">
      Nenhum canal autorizado. Vá em
      <span class="link-gold" onclick="location.hash='#/apis'">APIs & Conexões</span>
      → <b>Canal do YouTube</b> → <b>🔗 Autorizar</b>.<br>
      <small style="color:var(--faint)">Sem o OAuth do canal não há como publicar:
      upload é escrita, e a API key só lê.</small></div>`;
  }

  const r = d.resumo || {};
  const card = (rotulo, valor, extra = "") => `<div class="card">
      <small style="color:var(--muted)">${rotulo}</small>
      <h2 style="margin:4px 0">${valor}</h2>
      <small style="color:var(--faint)">${extra}</small></div>`;
  $("#pub-resumo").innerHTML =
    card("Canal", esc(canal.titulo || "—"), d.autorizado ? "conectado" : "não autorizado") +
    card("Publicados", r.publicados ?? 0, `${r.janela_dias || 7} dias de acompanhamento`) +
    card("Views totais", fmtNum(r.views_total ?? 0), `${fmtNum(r.likes_total ?? 0)} likes`) +
    card("No corpus", r.no_corpus ?? 0, "vídeos nossos realimentando o baseline");

  const pubs = d.publicacoes || [];
  if (!pubs.length) {
    if (d.autorizado) {
      $("#pub-list").innerHTML = `<div class="card"><div class="empty">
        Nada publicado ainda. Gere um vídeo na
        <span class="link-gold" onclick="location.hash='#/fabrica'">Fábrica</span>
        e clique em <b>📤 Publicar</b> no job pronto.</div></div>`;
    }
    return;
  }

  $("#pub-list").innerHTML = `<div class="card"><table class="table">
    <thead><tr><th>Vídeo</th><th>Privacidade</th><th class="num">Views</th>
      <th class="num">Likes</th><th class="num">Velocidade</th><th>Evolução</th>
      <th>Última leitura</th><th></th></tr></thead>
    <tbody>${pubs.map(p => {
      const s = (p.snapshots || []).slice(-1)[0] || {};
      const serie = (p.snapshots || []).map(x => x.views || 0);
      const vel = s.views && s.idade_h ? (s.views / Math.max(1, s.idade_h)) : 0;
      const cls = { public: "green", unlisted: "gold", private: "gray" }[p.privacidade] || "gray";
      return `<tr>
        <td><b>${esc(p.titulo || "(sem título)")}</b><br>
          <a href="${esc(p.url)}" target="_blank" rel="noopener"
             style="font-size:11.5px;color:var(--cyan)">${esc(p.video_id)}</a>
          ${p.erro ? `<br><small style="color:var(--red)">${esc(p.erro)}</small>` : ""}</td>
        <td><span class="badge ${cls}">${esc(p.privacidade || "—")}</span></td>
        <td class="num"><b>${fmtNum(s.views || 0)}</b></td>
        <td class="num">${fmtNum(s.likes || 0)}</td>
        <td class="num">${vel ? fmtNum(Math.round(vel)) + "/h" : "—"}</td>
        <td>${serie.length > 1 ? sparkline(serie, 90, 26) : `<small style="color:var(--faint)">${serie.length} leitura</small>`}</td>
        <td style="color:var(--muted);font-size:12px">${esc((p.ultima_leitura || "—").slice(0, 16).replace("T", " "))}</td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick="syncUma('${p.id}')">↻</button>
          <button class="btn small danger" onclick="apagarPub('${p.id}')">✕</button></td>
      </tr>`;
    }).join("")}</tbody></table>
    <small style="color:var(--faint);display:block;margin-top:10px">
      Remover aqui apaga só o registro no MineraAI — o vídeo continua no YouTube.</small></div>`;
}

window.syncPublicacoes = async () => {
  toast("Consultando o YouTube…");
  try {
    const r = await api("/publicacoes/sync", { method: "POST" });
    toast(`${r.sincronizados} publicação(ões) atualizada(s)` +
      (r.falhas?.length ? ` · ${r.falhas.length} com erro` : ""), !!r.falhas?.length);
    viewPublicacoes();
  } catch (e) { toast(e.message, true); }
};

window.syncUma = async (id) => {
  try {
    await api(`/publicacoes/${id}/sync`, { method: "POST" });
    loadMe(); viewPublicacoes();
  } catch (e) { toast(e.message, true); }
};

window.apagarPub = async (id) => {
  if (!confirm("Remover o registro? O vídeo continua no YouTube.")) return;
  await api(`/publicacoes/${id}`, { method: "DELETE" });
  viewPublicacoes();
};

// ============================================================ MINERAÇÃO
async function viewMineracao() {
  $("#view").innerHTML = `
    <div class="page-head"><div>
      <h1>Mineração ⛏️</h1>
      <p>O modelo que o Virlo usa — <b>Orbit</b> (busca em fila) e <b>Comet</b>
      (monitor agendado) — rodando com as nossas fontes.</p>
    </div></div>
    <div class="grid cols-2">
      <div class="card">
        <h3>Novo Orbit — busca em fila</h3>
        <div class="field"><label>Palavras-chave (uma por linha)</label>
          <textarea id="orb-kw" rows="3" placeholder="skincare&#10;glass skin"></textarea></div>
        <div class="form-row" style="margin-top:8px">
          <div class="field grow"><label>Nome</label><input id="orb-name" placeholder="opcional" /></div>
          <div class="field grow"><label>Views mínimas</label><input id="orb-min" type="number" value="0" /></div>
        </div>
        <button class="btn primary" id="orb-go" style="margin-top:10px">⛏️ Minerar agora</button>
        <small style="color:var(--faint);display:block;margin-top:8px">10 créditos por Orbit.</small>
      </div>
      <div class="card">
        <h3>Novo Comet — monitor agendado</h3>
        <div class="field"><label>Palavras-chave (uma por linha)</label>
          <textarea id="cmt-kw" rows="3" placeholder="achadinhos de cozinha"></textarea></div>
        <div class="form-row" style="margin-top:8px">
          <div class="field grow"><label>Frequência</label>
            <select id="cmt-freq"><option value="6h">A cada 6h</option>
              <option value="daily" selected>Diário</option><option value="weekly">Semanal</option></select></div>
          <div class="field grow"><label>Nome</label><input id="cmt-name" placeholder="opcional" /></div>
        </div>
        <button class="btn primary" id="cmt-go" style="margin-top:10px">📡 Criar monitor</button>
        <small style="color:var(--faint);display:block;margin-top:8px">Cada ciclo custa 10 créditos.</small>
      </div>
    </div>
    <div class="section-title">Como o pipeline funciona</div>
    <div class="card" id="mining-explain">…</div>
    <div class="section-title">Orbits <button class="btn small" onclick="viewMineracao()">↻</button></div>
    <div class="card"><div id="orb-list">…</div></div>
    <div class="section-title">Comets (série temporal)</div>
    <div class="card"><div id="cmt-list">…</div></div>`;

  $("#orb-go").onclick = () => criarOrbit();
  $("#cmt-go").onclick = () => criarComet();
  carregarExplicacao();
  carregarOrbits();
  carregarComets();
}

async function carregarExplicacao() {
  const el = $("#mining-explain");
  if (!el) return;
  const d = await api("/mining/como-funciona");
  el.innerHTML = `<p style="color:var(--muted);font-size:13px">${esc(d.resumo)}</p>
    <table class="table"><tbody>
      ${d.etapas.map(e => `<tr><td style="width:180px"><b>${esc(e.etapa || e.etaapa || "")}</b></td>
        <td style="color:var(--muted)">${esc(e.detalhe)}</td></tr>`).join("")}
    </tbody></table>
    <small style="color:var(--faint);display:block;margin-top:10px">${esc(d.diferenca)}</small>`;
}

const linhasParaLista = (txt) => txt.split("\n").map(x => x.trim()).filter(Boolean);

window.criarOrbit = async () => {
  const keywords = linhasParaLista($("#orb-kw").value);
  if (!keywords.length) return toast("Informe ao menos uma palavra-chave", true);
  toast("Minerando…");
  try {
    const r = await api("/mining/orbits", { method: "POST", body: {
      name: $("#orb-name").value.trim(), keywords, min_views: +$("#orb-min").value || 0 } });
    loadMe();
    toast(`Orbit pronto: ${r.orbit.report?.videos_unicos || 0} vídeos, ${r.orbit.report?.outliers || 0} outliers`);
    carregarOrbits();
  } catch (e) { toast(e.message, true); }
};

window.criarComet = async () => {
  const keywords = linhasParaLista($("#cmt-kw").value);
  if (!keywords.length) return toast("Informe ao menos uma palavra-chave", true);
  try {
    await api("/mining/comets", { method: "POST", body: {
      name: $("#cmt-name").value.trim(), keywords, frequency: $("#cmt-freq").value } });
    toast("Monitor criado 📡");
    carregarComets();
  } catch (e) { toast(e.message, true); }
};

async function carregarOrbits() {
  const el = $("#orb-list");
  if (!el) return;
  const d = await api("/mining/orbits");
  if (!d.orbits.length) {
    el.innerHTML = `<div class="empty">Nenhum Orbit ainda — o primeiro vira a base do Radar.</div>`;
    return;
  }
  el.innerHTML = `<table class="table"><thead><tr>
      <th>Orbit</th><th>Keywords</th><th class="num">Vídeos</th><th class="num">Outliers</th>
      <th>Status</th><th></th></tr></thead><tbody>
    ${d.orbits.map(o => `<tr>
      <td><b>${esc(o.name)}</b><br><small style="color:var(--faint)">${o.created_at?.slice(0, 16).replace("T", " ")}</small></td>
      <td style="color:var(--muted);font-size:12px">${esc((o.keywords || []).join(", ")).slice(0, 60)}</td>
      <td class="num">${o.report?.videos_unicos ?? "—"}</td>
      <td class="num"><b style="color:var(--gold)">${o.report?.outliers ?? "—"}</b></td>
      <td><span class="badge ${o.status === "completed" ? "green" : "gray"}">${o.status}</span></td>
      <td><button class="btn small" onclick="verOrbit('${o.id}')">👁</button>
          <button class="btn small ghost" onclick="apagarOrbit('${o.id}')">🗑</button></td>
    </tr>`).join("")}</tbody></table>`;
}

window.verOrbit = async (id) => {
  const d = await api(`/mining/orbits/${id}?limit=25`);
  openModal(`<h2>⛏️ ${esc(d.orbit.name)}</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">
      <span class="badge gold">${d.orbit.report?.videos_unicos || 0} vídeos</span>
      <span class="badge violet">${d.orbit.report?.outliers || 0} outliers</span>
      <span class="badge gray">mediana ${fmtNum(d.orbit.report?.mediana_views || 0)}</span>
      ${Object.entries(d.orbit.fontes || {}).map(([f, n]) => `<span class="badge cyan">${f}: ${n}</span>`).join("")}
    </div>
    <table class="table"><tbody>
      ${(d.outliers.length ? d.outliers : d.videos).slice(0, 15).map(v => `<tr>
        <td><b>${esc(v.title || "—")}</b><br><small style="color:var(--muted)">${esc(v.handle || "")} · ${v.platform}</small></td>
        <td class="num">${fmtNum(v.views)}</td>
        <td class="num" style="color:var(--gold)">${v.outlier_ratio}x</td>
        <td class="num">${v.outlier_score}</td>
      </tr>`).join("") || '<tr><td>Sem vídeos — configure uma fonte real (YouTube/Virlo).</td></tr>'}
    </tbody></table>`);
};

window.apagarOrbit = async (id) => {
  if (!confirm("Apagar este Orbit?")) return;
  await api(`/mining/orbits/${id}`, { method: "DELETE" });
  carregarOrbits();
};

async function carregarComets() {
  const el = $("#cmt-list");
  if (!el) return;
  const d = await api("/mining/comets");
  if (!d.comets.length) {
    el.innerHTML = `<div class="empty">Nenhum monitor ainda. O Comet empilha observações
      a cada ciclo — é o que transforma busca em série temporal.</div>`;
    return;
  }
  el.innerHTML = d.comets.map(c => {
    const serie = (c.series || []).map(s => s.videos);
    const ultimo = (c.series || [])[(c.series || []).length - 1];
    return `<div class="agent-row">
      <div>
        <b>${esc(c.name)}</b> <span class="badge cyan">${c.frequency}</span>
        <br><small style="color:var(--muted)">${esc((c.keywords || []).join(", ")).slice(0, 70)}</small>
        <br><small style="color:var(--faint)">
          ${c.last_run ? `último ciclo: ${c.last_run} · ${ultimo?.videos ?? 0} vídeos · ${ultimo?.outliers ?? 0} outliers` : "nunca executado"}
          ${c.next_run ? ` · próxima: ${c.next_run.replace("T", " ").replace("Z", "")}` : ""}</small>
      </div>
      <div style="display:flex;align-items:center;gap:10px">
        ${serie.length > 1 ? sparkline(serie, 90, 26) : ""}
        <button class="btn small primary" onclick="rodarComet('${c.id}')">▶ Ciclo</button>
        <button class="btn small ghost" onclick="apagarComet('${c.id}')">🗑</button>
      </div></div>`;
  }).join("");
}

window.rodarComet = async (id) => {
  try {
    await api(`/mining/comets/${id}/run`, { method: "POST" });
    loadMe(); carregarComets();
    toast("Ciclo executado");
  } catch (e) { toast(e.message, true); }
};

window.apagarComet = async (id) => {
  if (!confirm("Apagar este monitor?")) return;
  await api(`/mining/comets/${id}`, { method: "DELETE" });
  carregarComets();
};

// ------------------------------------------------------------------ boot
window.saveToLibrary = saveToLibrary;
window.copyText = copyText;
window.openProduct = window.openProduct;
window.addEventListener("hashchange", router);
loadMe();
loadStatus().then(router);
