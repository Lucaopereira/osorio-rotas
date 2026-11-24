"""A tela do despacho (`/despacho/real` e `/despacho/treino` no servidor gerencial).

Entra o pedido (canal, endereço ou bairro, tipo) e o robô responde na hora: qual motoboy, quando sai, quando chega.
No treino: cenários (noites reais, planilha, digitado), relógio acelerado e piloto automático. A tela pergunta o estado
a cada 2 segundos; contagens regressivas andam no navegador entre uma resposta e outra.
"""
from __future__ import annotations

import html
import json
import math

from robo_rotas import despacho as D, itajuba
from robo_rotas.simulador_pagina import CORES_MOTO

FUNDO = itajuba.FUNDO
MARGEM = 0.010


def _mundo(lat, lon, z):
    n = 256 * 2 ** z
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def recorte():
    lats = [b[1] for b in itajuba.BAIRROS] + [itajuba.LOJA[0]]
    lons = [b[2] for b in itajuba.BAIRROS] + [itajuba.LOJA[1]]
    x0, y0 = _mundo(max(lats) + MARGEM, min(lons) - MARGEM, FUNDO["z"])
    x1, y1 = _mundo(min(lats) - MARGEM, max(lons) + MARGEM, FUNDO["z"])
    x0, y0 = max(0, int(x0 - FUNDO["px0"])), max(0, int(y0 - FUNDO["py0"]))
    x1, y1 = min(FUNDO["w"], int(x1 - FUNDO["px0"])), min(FUNDO["h"], int(y1 - FUNDO["py0"]))
    return x0, y0, x1, y1


def fundo_base64():
    import base64
    import io
    from pathlib import Path
    try:
        from PIL import Image
    except ImportError:
        return None
    p = Path(__file__).resolve().parent.parent / "robo_rotas" / "tela" / FUNDO["arquivo"]
    if not p.exists():
        return None
    x0, y0, x1, y1 = recorte()
    img = Image.open(p).convert("RGB").crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


EMOJI = {"lanche": "🍔", "marmita": "🍱", "poucas latas": "🥫", "fardo ou garrafas": "📦",
         "uma caixa de litrão": "🍺", "duas caixas de litrão": "🍺🍺"}
CURTO = {"lanche": "Lanche", "marmita": "Marmita", "poucas latas": "Latas", "fardo ou garrafas": "Fardo",
         "uma caixa de litrão": "1 caixa", "duas caixas de litrão": "2 caixas"}
CANAL = {"iFood Burguer": ("iF", "#d0302f"), "iFood Marmita": ("MA", "#e06d0b"), "Zé": ("Zé", "#d4a800"),
         "Site": ("SI", "#6a2a9a"), "WhatsApp": ("WA", "#1f8f4e")}

CSS = r"""
:root{--bg:#f3f4f6;--card:#fff;--ink:#141920;--muted:#5f6876;--line:#dfe3e8;--soft:#f1f3f6;--acc:#c2410c;--acc2:#ea580c;
--ok:#15803d;--okbg:#dcfce7;--warn:#a16207;--warnbg:#fef3c7;--late:#b91c1c;--latebg:#fee2e2;--info:#1d4ed8;--infobg:#dbeafe;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1116;--card:#171b22;--ink:#e8ecf1;--muted:#9aa4b1;--line:#2a313b;--soft:#12161c;
--acc:#f97316;--acc2:#fb923c;--ok:#4ade80;--okbg:#0f2a19;--warn:#fbbf24;--warnbg:#2d2208;--late:#f87171;--latebg:#3a1414;--info:#93c5fd;--infobg:#0f1f3d;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e1116;--card:#171b22;--ink:#e8ecf1;--muted:#9aa4b1;--line:#2a313b;--soft:#12161c;--acc:#f97316;--acc2:#fb923c;
--ok:#4ade80;--okbg:#0f2a19;--warn:#fbbf24;--warnbg:#2d2208;--late:#f87171;--latebg:#3a1414;--info:#93c5fd;--infobg:#0f1f3d;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
button,input,select{font:inherit;color:inherit}a{color:inherit}
.topo{position:sticky;top:0;z-index:20;background:var(--card);border-bottom:1px solid var(--line)}
.topo .in{max-width:1400px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
.marca{font-weight:800;font-size:20px;letter-spacing:-.01em}
.modos{display:flex;background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:3px}
.modos a{text-decoration:none;padding:5px 14px;border-radius:999px;font-weight:600;font-size:14px;color:var(--muted)}
.modos a.on{background:var(--ink);color:var(--card)}
.relogio{font:800 24px/1 ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
.selo{font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;background:var(--warnbg);color:var(--warn)}
.selo.vivo{background:var(--latebg);color:var(--late)}.selo.vivo::before{content:"● "}
.dir{margin-left:auto;display:flex;gap:10px;align-items:center;font-size:14px}
.ico{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:5px 10px;cursor:pointer}
.wrap{max-width:1400px;margin:0 auto;padding:14px 16px 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin-bottom:14px}
.card h2{margin:0 0 10px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.treino .linha{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center}
.treino select{padding:7px 10px;border:1px solid var(--line);border-radius:10px;background:var(--card);max-width:100%}
.treino .desc{color:var(--muted);font-size:13.5px;margin:8px 0 0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg button{border:0;background:var(--card);padding:6px 11px;cursor:pointer;font-weight:600}.seg button.on{background:var(--ink);color:var(--card)}
.bt{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:7px 12px;cursor:pointer;font-weight:600}
.bt:hover{border-color:var(--muted)}.bt.prim{background:var(--acc);border-color:var(--acc);color:#fff}.bt.prim:hover{background:var(--acc2)}
.bt.mini{padding:4px 9px;font-size:13px;font-weight:600}.bt.ok{background:var(--ok);border-color:var(--ok);color:#fff}
.bt:disabled{opacity:.45;cursor:default}
.interruptor{display:inline-flex;gap:8px;align-items:center;cursor:pointer;font-weight:600}
.interruptor input{appearance:none;width:38px;height:22px;border-radius:999px;background:var(--line);position:relative;cursor:pointer;transition:.2s}
.interruptor input::after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.2s}
.interruptor input:checked{background:var(--ok)}.interruptor input:checked::after{left:19px}
.barra{height:6px;background:var(--soft);border-radius:999px;overflow:hidden;margin-top:10px}.barra i{display:block;height:100%;background:var(--acc)}
.kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;margin-bottom:14px}
@media (max-width:900px){.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:9px 12px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.kpi span{font-size:12.5px;color:var(--muted)}
.kpi.ruim b{color:var(--late)}
.grade{display:grid;grid-template-columns:380px minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:1000px){.grade{grid-template-columns:minmax(0,1fr)}}
.lado{position:sticky;top:70px}@media (max-width:1000px){.lado{position:static}}
label.rot{display:block;font-size:12.5px;font-weight:600;color:var(--muted);margin:12px 0 5px}
.pills{display:flex;flex-wrap:wrap;gap:6px}
.pills label{cursor:pointer}.pills input{position:absolute;opacity:0;pointer-events:none}
.pills span{display:inline-flex;align-items:center;gap:5px;border:1.5px solid var(--line);border-radius:10px;padding:6px 10px;font-weight:600;font-size:14px;background:var(--card)}
.pills input:checked+span{border-color:var(--ink);background:var(--ink);color:var(--card)}
.pills input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px}
.tag{display:inline-block;font-size:11px;font-weight:800;border-radius:5px;padding:1px 5px;color:#fff;margin-right:5px;vertical-align:1px}
.campo{position:relative}
.campo input[type=text],.campo select,input.num{width:100%;padding:10px 11px;border:1.5px solid var(--line);border-radius:11px;background:var(--card)}
.campo input:focus,.campo select:focus,input.num:focus{outline:none;border-color:var(--info)}
.sug{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:var(--card);border:1px solid var(--line);border-radius:12px;
box-shadow:0 10px 30px rgba(0,0,0,.14);z-index:30;max-height:300px;overflow:auto;display:none}
.sug div{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--line)}.sug div:last-child{border:0}
.sug div.on,.sug div:hover{background:var(--soft)}.sug small{color:var(--muted)}
.achado{font-size:13px;margin-top:6px;min-height:19px}.achado.ok{color:var(--ok)}.achado.mais{color:var(--warn)}
.tempos{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.tempos label{font-size:12px;color:var(--muted);font-weight:600}
.tempos input{padding:8px 9px;margin-top:3px}
.resposta{margin-top:12px;border-radius:12px;padding:12px 14px;font-size:15px;display:none}
.resposta.ok{display:block;background:var(--okbg);color:var(--ok)}.resposta.espera{display:block;background:var(--warnbg);color:var(--warn)}
.resposta .grande{font-size:19px;font-weight:800;display:block;margin-bottom:2px}.resposta button{margin-top:6px}
.dica{color:var(--muted);font-size:12.5px;margin:10px 0 0}
.motos{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,250px),1fr));gap:10px}
.moto{border:1.5px solid var(--line);border-radius:14px;padding:11px 12px;background:var(--card);display:flex;flex-direction:column;gap:6px}
.moto.agora{border-color:var(--ok);box-shadow:0 0 0 3px var(--okbg)}
.moto .cab{display:flex;align-items:center;gap:8px;font-weight:800;font-size:16px}
.bola{width:12px;height:12px;border-radius:50%;flex:none;display:inline-block}
.chip{font-size:11.5px;font-weight:700;border-radius:999px;padding:1px 8px;margin-left:auto}
.chip.loja{background:var(--infobg);color:var(--info)}.chip.rua{background:var(--warnbg);color:var(--warn)}.chip.fora{background:var(--soft);color:var(--muted)}
.sair{display:inline-block;background:var(--ok);color:#fff;border-radius:8px;padding:2px 8px;font-weight:800;font-size:13px;animation:pulsa 1.4s infinite}
@keyframes pulsa{50%{opacity:.55}}
.moto .st{font-size:13.5px;color:var(--muted)}.moto ul{margin:0;padding:0;list-style:none;font-size:13.5px}
.moto li{padding:3px 0;border-top:1px dashed var(--line)}.moto li:first-child{border:0}
.moto .acoes{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}
.prog{height:5px;background:var(--soft);border-radius:999px;overflow:hidden}.prog i{display:block;height:100%}
.mapa{border-radius:14px;overflow:hidden;border:1px solid var(--line);background:var(--soft)}.mapa svg{display:block;width:100%;height:auto}
.legenda{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--muted);margin-top:8px}
.rolar{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px;min-width:860px}
th{font-size:12px;color:var(--muted);font-weight:700;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}tr.ent td{opacity:.5}
td select{padding:5px 7px;border:1px solid var(--line);border-radius:8px;background:var(--card);max-width:150px}
.muted{color:var(--muted)}.atr{color:var(--late);font-weight:700}.okc{color:var(--ok);font-weight:600}.am{color:var(--warn);font-weight:600}
.res{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.res div{background:var(--soft);border-radius:12px;padding:10px 12px}.res b{display:block;font-size:22px}.res span{font-size:12.5px;color:var(--muted)}
.fim{background:var(--okbg);color:var(--ok);border-radius:12px;padding:10px 14px;font-weight:700;margin-bottom:10px;display:none}
.aviso{background:var(--warnbg);color:var(--warn);border-radius:12px;padding:9px 12px;font-size:13.5px;margin-top:8px}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);color:var(--card);padding:10px 16px;border-radius:12px;
font-weight:600;z-index:50;opacity:0;transition:.25s;pointer-events:none;max-width:min(92vw,560px)}.toast.on{opacity:1}
.vazio{color:var(--muted);text-align:center;padding:18px}
"""

JS = r"""
const ESP = %ESPACO%, CORES = %CORES%, CANAL = %CANAL%, EMOJI = %EMOJI%, CURTO = %CURTO%, PADRAO = %PADRAO%;
const F = %FUNDO%;
const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const API = '/api/despacho/' + ESP;
let E = null, recebido = 0, somLigado = false, avisados = new Set(), ultimoCriado = null, escolhida = null;

// ---------- utilidades ----------
const n = 256 * 2 ** F.z;
const px = (lat, lon) => { const s = Math.sin(lat * Math.PI / 180);
  return [(lon + 180) / 360 * n - F.px0 - F.x0, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n - F.py0 - F.y0]; };
const agoraCli = () => !E ? Date.now() : E.agora + (E.relogio.pausado ? 0 : (Date.now() - recebido) * E.relogio.vel);
const hm = (ms) => { const d = new Date(ms); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
const mins = (ms) => Math.round(ms / 60000);
const tag = (p) => `<span class="tag" style="background:${CANAL[p.canal][1]}">${CANAL[p.canal][0]}</span>${esc(p.num)}`;
const motoDe = (id) => E.motos.find((m) => m.id === id);
const cor = (m) => CORES[(m?.cor ?? 0) % CORES.length];
function toast(t) { const el = $('#toast'); el.textContent = t; el.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 3200); }

async function api(caminho, corpo, metodo) {
  const op = {method: metodo || (corpo === undefined ? 'GET' : 'POST'), credentials: 'same-origin'};
  if (corpo instanceof FormData) op.body = corpo; else if (corpo !== undefined) { op.headers = {'Content-Type': 'application/json'}; op.body = JSON.stringify(corpo); }
  const r = await fetch(caminho, op);
  if (r.status === 401) { location.href = '/entrar'; throw new Error('sessão'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.erro || ('erro ' + r.status));
  return j;
}
async function acao(caminho, corpo) {
  try { const j = await api(API + '/' + caminho, corpo ?? {}); if (j.estado || j.pedidos) aplica(j.estado || j); else await atualiza(); return j; }
  catch (e) { if (e.message !== 'sessão') toast(e.message); return null; }
}
async function atualiza() { try { aplica(await api(API + '/estado')); } catch (e) { $('#relogio').textContent = 'sem conexão'; } }
function aplica(est) { E = est; recebido = Date.now(); desenha(); }

// ---------- som ----------
function bip() { if (!somLigado) return; try { const c = new (window.AudioContext || window.webkitAudioContext)(), o = c.createOscillator(), g = c.createGain();
  o.frequency.value = 880; g.gain.value = .08; o.connect(g); g.connect(c.destination); o.start(); setTimeout(() => { o.frequency.value = 1175; }, 140); setTimeout(() => { o.stop(); c.close(); }, 300);
  navigator.vibrate && navigator.vibrate(120); } catch (e) {} }
$('#som').addEventListener('click', () => { somLigado = !somLigado; $('#som').textContent = somLigado ? '🔔 Som ligado' : '🔕 Som'; if (somLigado) bip(); });

// ---------- formulário ----------
const form = $('#form');
function canalSel() { return form.canal.value; }
function tipoSel() { return form.tipo.value; }
function padroes() {
  const t = tipoSel(), c = canalSel(), comida = t === 'lanche' || t === 'marmita';
  form.preparo_min.placeholder = PADRAO.preparo[comida ? t : 'bebida']; form.prazo_min.placeholder = PADRAO.prazo[c];
}
form.addEventListener('change', (e) => {
  if (e.target.name === 'canal') { const c = canalSel(); const t = c === 'Zé' ? 'fardo ou garrafas' : c === 'iFood Marmita' ? 'marmita' : (['lanche','marmita'].includes(tipoSel()) ? tipoSel() : 'lanche');
    form.querySelector(`input[name=tipo][value="${t}"]`).checked = true; }
  padroes();
});
padroes();

// endereço com sugestões do mapa local
const end = $('#endereco'), lista = $('#sug'), achado = $('#achado');
let busca = null, itens = [], sel = -1;
function mostraAchado() {
  if (escolhida && escolhida.tipo === 'ponto') { achado.className = 'achado ok'; achado.innerHTML = `📌 Ponto da localização colada · ${esc(escolhida.bairro)}`; return; }
  if (escolhida) { achado.className = 'achado ok'; achado.innerHTML = `📍 ${esc(escolhida.rua)} · ${esc(escolhida.bairro)} <span class="muted">(pela rua)</span>`; return; }
  achado.className = 'achado mais'; achado.textContent = end.value.trim() ? 'Escolha a rua da lista, ou informe o bairro.' : '';
}
end.addEventListener('input', () => {
  escolhida = null; mostraAchado(); clearTimeout(busca);
  const q = end.value.trim(); if (q.length < 3) { lista.style.display = 'none'; return; }
  busca = setTimeout(async () => {
    try { const j = await api('/api/mapa/buscar?q=' + encodeURIComponent(q) + '&bairro=' + encodeURIComponent(form.bairro.value));
      if (j.ponto) { escolhida = {tipo: 'ponto', ...j.ponto}; form.bairro.value = j.ponto.bairro; lista.style.display = 'none'; mostraAchado(); return; }
      itens = (j.bairros || []).map((b) => ({bairro: b, soBairro: true})).concat(j.ruas); sel = itens.length ? 0 : -1;
      lista.innerHTML = itens.map((r, i) => `<div data-i="${i}" class="${i === 0 ? 'on' : ''}">${r.soBairro ? '🏘 Bairro ' + esc(r.bairro) + ' <small>· centro do bairro</small>' : '📍 ' + esc(r.rua) + ' <small>· ' + esc(r.bairro) + '</small>'}</div>`).join('')
        || '<div class="muted" style="cursor:default">Nenhuma rua com esse nome no mapa. Informe o bairro.</div>';
      lista.style.display = 'block';
    } catch (e) {} }, 160);
});
function escolhe(i) {
  const r = itens[i]; if (!r) return;
  if (r.soBairro) { form.bairro.value = r.bairro; end.value = ''; escolhida = null; lista.style.display = 'none';
    achado.className = 'achado ok'; achado.innerHTML = `🏘 Centro do bairro ${esc(r.bairro)} <span class="muted">(sem a rua, o ponto é o centro do bairro)</span>`; return; }
  const num = (end.value.match(/[, ]\s*(\d{1,5})\s*$/) || [])[1];
  end.value = r.rua + (num ? ', ' + num : ', '); escolhida = {tipo: 'rua', ...r}; form.bairro.value = r.bairro;
  lista.style.display = 'none'; mostraAchado(); end.focus();
}
lista.addEventListener('mousedown', (e) => { const d = e.target.closest('[data-i]'); if (d) { e.preventDefault(); escolhe(+d.dataset.i); } });
end.addEventListener('keydown', (e) => {
  if (lista.style.display !== 'block' || !itens.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : itens.length - 1)) % itens.length;
    $$('#sug div').forEach((d, i) => d.classList.toggle('on', i === sel)); }
  else if (e.key === 'Enter' || e.key === 'Tab') { if (sel >= 0) { e.preventDefault(); escolhe(sel); } }
  else if (e.key === 'Escape') lista.style.display = 'none';
});
end.addEventListener('blur', () => setTimeout(() => lista.style.display = 'none', 150));

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(form), corpo = Object.fromEntries(f.entries());
  const bt = $('#mandar'); bt.disabled = true;
  const j = await acao('pedido', corpo); bt.disabled = false;
  if (!j) return;
  const p = j.pedido, m = motoDe(p.moto), r = $('#resposta');
  ultimoCriado = p.ref;
  const onde = p.rua ? `${esc(p.rua)}${p.numero ? ', ' + esc(p.numero) : ''} · ${esc(p.bairro)}` : esc(p.bairro);
  if (m) { r.className = 'resposta ok';
    r.innerHTML = `<span class="grande">🛵 ${esc(m.nome)} leva</span>${tag(p)} ${EMOJI[p.tipo]} ${onde}<br>Sai ${esc(p.sai_hm)} · chega ${esc(p.chega_hm)} · prazo ${esc(p.prazo_hm)}${p.junto > 1 ? '<br>Vai junto com outro pedido no caminho.' : ''}`;
  } else { r.className = 'resposta espera';
    r.innerHTML = `<span class="grande">⏳ Na fila</span>${tag(p)} ${onde}<br>Todos os motoboys já têm saída. Ganha motoboy quando alguém sair da loja.`; }
  if (j.aviso) r.innerHTML += `<br><b>${esc(j.aviso)}</b>`;
  r.innerHTML += `<br><button class="bt mini" type="button" id="desfazer">Desfazer</button>`;
  $('#desfazer').onclick = async () => { await acao('cancelar/' + ultimoCriado); r.className = 'resposta'; toast('Pedido desfeito.'); };
  form.num.value = ''; end.value = ''; form.bairro.value = ''; escolhida = null; form.preparo_min.value = ''; form.prazo_min.value = ''; mostraAchado(); end.focus();
});
$('#form-moto').addEventListener('submit', async (e) => { e.preventDefault(); const nome = e.target.nome.value.trim(); if (!nome) return;
  if (await acao('moto', {nome})) { e.target.nome.value = ''; toast(nome + ' entrou no turno.'); } });

// ---------- desenho ----------
function desenha() {
  const agora = agoraCli();
  $('#relogio').textContent = hm(agora);
  if (ESP === 'treino') desenhaTreino();
  const ab = E.pedidos.filter((p) => p.status !== 'entregue');
  const r = E.resumo;
  const k = [['na cozinha', ab.filter((p) => p.status === 'cozinha').length], ['prontos', ab.filter((p) => p.status === 'pronto').length],
    ['na rua', ab.filter((p) => p.status === 'rua').length], ['entregues', r.entregues], ['tempo médio', r.tempo_medio != null ? Math.round(r.tempo_medio) + ' min' : '·'],
    ['atrasados', r.atrasados_pct != null ? r.atrasados_pct + '%' : '·', r.atrasados_pct >= 10], ['comida fria', r.frias_pct != null ? r.frias_pct + '%' : '·', r.frias_pct >= 10]];
  $('#kpis').innerHTML = k.map(([t, v, ruim]) => `<div class="kpi ${ruim ? 'ruim' : ''}"><b>${v}</b><span>${t}</span></div>`).join('');
  desenhaMotos(agora); desenhaFila(agora); desenhaMapa(agora); desenhaResultado();
}

function rotaTexto(m, paradas) {
  return `${m.nome}\n` + paradas.map((p, i) => `${i + 1}. ${CANAL[p.canal][0]} ${p.num} · ${p.rua ? p.rua + (p.numero ? ', ' + p.numero : '') + ' · ' : ''}${p.bairro} (${CURTO[p.tipo]})`).join('\n');
}
function rotaLink(paradas) {
  const ll = (p) => p.lat.toFixed(6) + ',' + p.lon.toFixed(6), loja = E.loja[0].toFixed(6) + ',' + E.loja[1].toFixed(6);
  return `https://www.google.com/maps/dir/?api=1&origin=${loja}&destination=${ll(paradas[paradas.length - 1])}&travelmode=driving` +
    (paradas.length > 1 ? '&waypoints=' + paradas.slice(0, -1).map(ll).join('%7C') : '');
}

function desenhaMotos(agora) {
  const ped = (r) => E.pedidos.find((p) => p.ref === r);
  const html = E.motos.map((m) => {
    const s = E.saidas[m.id], c = cor(m);
    let chip, corpo = '', acoes = '', classe = '';
    if (m.status === 'rua') {
      chip = '<span class="chip rua">na rua</span>';
      const total = Math.max(1, m.volta_prev - m.saiu), feito = Math.min(1, Math.max(0, (agora - m.saiu) / total));
      const paradas = m.saida.map(ped).filter(Boolean);
      corpo = `<div class="st">volta em ${Math.max(0, mins(m.volta_prev - agora))} min · ${esc(m.volta_hm)}</div><div class="prog"><i style="width:${feito * 100}%;background:${c}"></i></div>
        <ul>${paradas.map((p) => `<li>${tag(p)} ${EMOJI[p.tipo]} ${esc(p.bairro)} · ${p.status === 'entregue' ? '<span class="okc">entregue</span>' : 'chega ' + esc(p.chega_hm)}</li>`).join('')}</ul>`;
      if (s && s.paradas.length) corpo += `<div class="st">depois: ${s.paradas.map(ped).filter(Boolean).map((p) => tag(p)).join(' ')}</div>`;
      acoes = `<button class="bt mini" data-a="moto/${m.id}/voltou">Voltou</button>` + (paradas.length ? ` <a class="bt mini" target="_blank" rel="noopener" href="${rotaLink(paradas)}">🗺 Rota</a>` : '');
    } else if (m.status === 'fora') {
      chip = '<span class="chip fora">pausado</span>'; corpo = '<div class="st">Fora da loja: o robô não conta com ele.</div>';
      acoes = `<button class="bt mini" data-a="moto/${m.id}/pausar">Voltou para a loja</button> <button class="bt mini" data-a="moto/${m.id}/tirar">Tirar do turno</button>`;
    } else {
      chip = '<span class="chip loja">na loja</span>';
      if (s && s.paradas.length) {
        const paradas = s.paradas.map(ped).filter(Boolean);
        const prontos = paradas.filter((p) => p.status === 'pronto' || agora >= p.pronto_ms);
        if (s.agora) { classe = 'agora'; corpo = '<span class="sair">SAIR AGORA</span>'; }
        else corpo = `<div class="st">sai ${esc(s.sai)}${s.sai_ms > agora ? ' · em ' + mins(s.sai_ms - agora) + ' min' : ''}</div>`;
        corpo += `<ul>${paradas.map((p) => `<li>${tag(p)} ${EMOJI[p.tipo]} ${esc(p.bairro)} · ${agora >= p.pronto_ms ? '<span class="okc">pronto</span>' : 'cozinha ' + Math.max(0, mins(p.pronto_ms - agora)) + ' min'}</li>`).join('')}</ul>`;
        acoes = `<button class="bt mini ${s.agora ? 'ok' : ''}" data-a="moto/${m.id}/saiu" ${prontos.length ? '' : 'disabled'}>Saiu</button>` +
          ` <a class="bt mini" target="_blank" rel="noopener" href="${rotaLink(paradas)}">🗺 Rota</a> <button class="bt mini" data-copiar="${m.id}">📋 Copiar</button>`;
        if (s.agora && !avisados.has(m.id)) { avisados.add(m.id); bip(); }
      } else { corpo = '<div class="st">livre, esperando pedido</div>'; avisados.delete(m.id); }
      if (!s?.agora) avisados.delete(m.id);
      acoes += ` <button class="bt mini" data-a="moto/${m.id}/pausar">Pausar</button> <button class="bt mini" data-a="moto/${m.id}/tirar">Tirar</button>`;
    }
    return `<div class="moto ${classe}"><div class="cab"><span class="bola" style="background:${c}"></span>${esc(m.nome)} <span class="muted" style="font-weight:500;font-size:12.5px">${m.entregas || 0} entregas</span>${chip}</div>${corpo}<div class="acoes">${acoes}</div></div>`;
  }).join('');
  $('#motos').innerHTML = html || '<div class="vazio">Nenhum motoboy no turno. Cadastre ao lado para o robô começar a distribuir.</div>';
}

function desenhaFila(agora) {
  const opts = (p) => {
    const atual = motoDe(p.moto);
    const robo = !p.manual && atual ? `Robô: ${esc(atual.nome)}` : 'Robô decide';
    return `<select data-fixar="${p.ref}" aria-label="Motoboy do pedido ${esc(p.num)}"><option value="">${robo}</option>` +
      E.motos.filter((m) => m.status !== 'fora').map((m) => `<option value="${m.id}" ${p.manual && p.moto === m.id ? 'selected' : ''}>📌 ${esc(m.nome)}</option>`).join('') + '</select>';
  };
  const linhas = E.pedidos.slice().sort((a, b) => (a.status === 'entregue') - (b.status === 'entregue') || a.criado - b.criado).map((p) => {
    const onde = p.rua ? `${esc(p.rua)}${p.numero ? ', ' + esc(p.numero) : ''}<br><span class="muted">${esc(p.bairro)} · pela rua</span>`
      : p.precisao === 'ponto' ? `Localização colada<br><span class="muted">${esc(p.bairro)}</span>`
      : `${esc(p.bairro)}<br><span class="muted">${p.bairro_sorteado ? 'bairro sorteado' : 'centro do bairro'}</span>`;
    let coz;
    if (p.status === 'cozinha') coz = agora >= p.pronto_ms ? '<span class="okc">pronto</span>' : `na cozinha<br><span class="muted">pronto em ${Math.max(0, mins(p.pronto_ms - agora))} min</span>`;
    else if (p.status === 'pronto') { const esp = mins(agora - p.pronto_ms); coz = `<span class="${esp >= 10 ? 'atr' : 'okc'}">pronto há ${Math.max(0, esp)} min</span>`; }
    else if (p.status === 'rua') coz = '<span class="am">na rua</span>'; else coz = '<span class="muted">entregue</span>';
    const m = motoDe(p.moto);
    const quem = ['cozinha', 'pronto'].includes(p.status) ? opts(p) : (m ? `<span class="bola" style="background:${cor(m)}"></span> ${esc(m.nome)}` : '');
    let quando = '';
    if (['cozinha', 'pronto'].includes(p.status)) quando = p.sai_hm ? `sai ${esc(p.sai_hm)} · chega ${esc(p.chega_hm)}` : '<span class="atr">sem motoboy ainda</span>';
    else if (p.status === 'rua') quando = `chega ${esc(p.chega_hm)}`; else quando = `entregue ${hm(p.entregue)}`;
    const fim = p.status === 'entregue' ? p.entregue : null;
    const atraso = fim ? mins(fim - p.prazo_ms) : p.atraso;
    const selo = atraso > 0 ? ` <span class="atr">+${atraso} min</span>` : (p.status !== 'cozinha' && p.status !== 'pronto' || p.sai_hm ? ' <span class="okc">no prazo</span>' : '');
    const bts = (p.status === 'cozinha' ? `<button class="bt mini" data-a="pronto/${p.ref}">Pronto</button> ` : '') +
      (['cozinha', 'pronto'].includes(p.status) ? `<button class="bt mini" data-a="cancelar/${p.ref}" title="Cancelar pedido">✕</button>` : '');
    return `<tr class="${p.status === 'entregue' ? 'ent' : ''}"><td>${tag(p)}<br><span class="muted">${esc(p.criado_hm)}</span></td><td>${EMOJI[p.tipo]} ${CURTO[p.tipo]}</td>
      <td>${onde}</td><td>${coz}</td><td>${quem}</td><td>${quando}${selo}<br><span class="muted">prazo ${esc(p.prazo_hm)}</span></td><td>${bts}</td></tr>`;
  }).join('');
  $('#fila').innerHTML = linhas || '<tr><td colspan="7" class="vazio">Nenhum pedido ainda. Mande o primeiro pelo formulário ao lado.</td></tr>';
}

function trajeto(pts) { return pts.map((q) => px(q[0], q[1]).map((v) => v.toFixed(1)).join(',')).join(' '); }
function posNaPerna(pts, f) {
  if (pts.length === 1) return px(pts[0][0], pts[0][1]);
  const P = pts.map((q) => px(q[0], q[1])); let tot = 0; const seg = [];
  for (let i = 1; i < P.length; i++) { const d = Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]); seg.push(d); tot += d; }
  let alvo = tot * Math.max(0, Math.min(1, f));
  for (let i = 0; i < seg.length; i++) { if (alvo <= seg[i] || i === seg.length - 1) { const t = seg[i] ? alvo / seg[i] : 0;
    return [P[i][0] + (P[i + 1][0] - P[i][0]) * t, P[i][1] + (P[i + 1][1] - P[i][1]) * t]; } alvo -= seg[i]; }
}
function desenhaMapa(agora) {
  const g = [], linhas = [], motos = [];
  for (const [id, s] of Object.entries(E.saidas)) {
    const m = motoDe(id); if (!m || m.status !== 'loja' || !s.trajeto.length) continue;
    linhas.push(`<polyline points="${trajeto(s.trajeto)}" fill="none" stroke="${cor(m)}" stroke-width="3" stroke-dasharray="3 7" stroke-linecap="round" opacity=".9"/>`);
  }
  for (const m of E.motos) {
    if (m.status !== 'rua' || !m.pernas) continue;
    const c = cor(m); let pos = null;
    for (const p of m.pernas) {
      if (agora >= p.ate) continue;
      linhas.push(`<polyline points="${trajeto(p.pts)}" fill="none" stroke="${c}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>`);
      if (!pos && agora >= p.de) pos = posNaPerna(p.pts, (agora - p.de) / Math.max(1, p.ate - p.de));
    }
    if (!pos) pos = px(E.loja[0], E.loja[1]);
    motos.push(`<g><circle cx="${pos[0]}" cy="${pos[1]}" r="15" fill="${c}" stroke="#fff" stroke-width="3"/><text x="${pos[0]}" y="${pos[1] + 5}" text-anchor="middle" font-size="14" font-weight="800" fill="#fff">${esc(m.nome[0])}</text><title>${esc(m.nome)}</title></g>`);
  }
  for (const p of E.pedidos) {
    const [x, y] = px(p.lat, p.lon), c = CANAL[p.canal][1], t = `<title>${esc(p.canal)} ${esc(p.num)} · ${esc(p.rua || p.bairro)}</title>`;
    if (p.status === 'cozinha') g.push(`<circle cx="${x}" cy="${y}" r="9" fill="var(--card)" stroke="${c}" stroke-width="4">${t}</circle>`);
    else if (p.status === 'pronto') g.push(`<circle cx="${x}" cy="${y}" r="10" fill="${c}" stroke="#fff" stroke-width="3">${t}</circle>`);
    else if (p.status === 'rua') { const m = motoDe(p.moto); g.push(`<circle cx="${x}" cy="${y}" r="10" fill="${c}" stroke="${cor(m)}" stroke-width="5">${t}</circle>`); }
    else g.push(`<circle cx="${x}" cy="${y}" r="5" fill="#64748b" opacity=".55">${t}</circle>`);
  }
  $('#camada').innerHTML = linhas.join('') + g.join('') + motos.join('');
}

function desenhaResultado() {
  const r = E.resumo, el = $('#resultado');
  const itens = [['Entregues', r.entregues + ' de ' + r.pedidos], ['Tempo médio até a porta', r.tempo_medio != null ? Math.round(r.tempo_medio) + ' min' : '·'],
    ['Atrasados', r.atrasados_pct != null ? `${r.atrasados} (${r.atrasados_pct}%)` : '·'], ['Comida fria', r.frias_pct != null ? `${r.frias} (${r.frias_pct}%)` : '·'],
    ['Espera do pronto até sair', r.espera_media != null ? Math.round(r.espera_media) + ' min' : '·'], ['Pedidos por saída', r.por_saida ?? '·'], ['Km rodados', r.km]];
  el.innerHTML = itens.map(([t, v]) => `<div><b>${v}</b><span>${t}</span></div>`).join('');
  $('#fim').style.display = E.cenario && E.cenario.fim ? 'block' : 'none';
}

// ---------- treino ----------
function desenhaTreino() {
  const c = E.cenario, rel = E.relogio;
  $('#tocar').textContent = rel.pausado ? '▶ Tocar' : '⏸ Pausar';
  $$('#vel button').forEach((b) => b.classList.toggle('on', +b.dataset.v === rel.vel));
  $('#piloto').checked = !!(c && c.piloto);
  $('#selo-vel').textContent = rel.pausado ? 'parado' : `treino ${rel.vel}×`;
  if (c) {
    $('#progresso').style.display = 'block';
    $('#prog-txt').textContent = `${c.titulo} · ${c.chegaram} de ${c.total} pedidos chegaram`;
    $('#prog-barra').style.width = (c.total ? 100 * c.chegaram / c.total : 0) + '%';
    $('#fora').innerHTML = c.fora && c.fora.length ? `<div class="aviso">${c.fora.length} pedido(s) da noite ficaram de fora porque o bairro não está no mapa: ${c.fora.slice(0, 4).map(esc).join('; ')}${c.fora.length > 4 ? '…' : ''}</div>` : '';
  } else $('#progresso').style.display = 'none';
}
async function carregaCenarios() {
  try { const j = await api('/api/despacho/cenarios');
    $('#cenario').innerHTML = j.cenarios.map((c) => `<option value="${esc(c.nome)}" data-m="${c.motoboys}" data-d="${esc(c.descricao)}">${esc(c.titulo)}</option>`).join('');
    mostraDescricao(); } catch (e) {}
}
function mostraDescricao() { const o = $('#cenario').selectedOptions[0]; if (!o) return; $('#cen-desc').textContent = o.dataset.d; $('#cen-motos').value = o.dataset.m; }

// ---------- cliques ----------
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-a]');
  if (b) { const a = b.dataset.a;
    if (a.endsWith('/tirar') && !confirm('Tirar este motoboy do turno?')) return;
    if (a.startsWith('cancelar') && !confirm('Cancelar este pedido?')) return;
    b.disabled = true; await acao(a); b.disabled = false; return; }
  const cp = e.target.closest('[data-copiar]');
  if (cp) { const m = motoDe(cp.dataset.copiar), s = E.saidas[m.id];
    const txt = rotaTexto(m, s.paradas.map((r) => E.pedidos.find((p) => p.ref === r)).filter(Boolean)) + `\nVolta ${s.volta}`;
    try { await navigator.clipboard.writeText(txt); toast('Rota copiada: cole no WhatsApp do motoboy.'); } catch (er) { prompt('Copie a rota:', txt); } }
});
document.addEventListener('change', async (e) => {
  const s = e.target.closest('[data-fixar]');
  if (s) { await acao('fixar/' + s.dataset.fixar, {moto: s.value || null}); toast(s.value ? 'Pedido fixado no motoboy escolhido.' : 'O robô volta a decidir esse pedido.'); }
});
if (ESP === 'treino') {
  $('#cenario').addEventListener('change', mostraDescricao);
  $('#carregar').addEventListener('click', async () => { if (E && E.pedidos.length && !confirm('Começar este cenário? O treino atual é apagado.')) return;
    const j = await acao('cenario', {nome: $('#cenario').value, motoboys: $('#cen-motos').value, piloto: true}); if (j) toast('Cenário pronto. Toque ▶ para começar.'); });
  $('#tocar').addEventListener('click', () => acao('relogio/' + (E.relogio.pausado ? 'tocar' : 'pausar')));
  $$('#vel button').forEach((b) => b.addEventListener('click', () => acao('relogio/velocidade', {vel: +b.dataset.v})));
  $('#mais5').addEventListener('click', () => acao('relogio/avancar', {min: 5}));
  $('#piloto').addEventListener('change', (e) => acao('piloto', {ligado: e.target.checked}));
  $('#inventado').addEventListener('click', () => acao('simular'));
  $('#arquivo').addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('arquivo', f); fd.append('motoboys', $('#cen-motos').value);
    try { const j = await api(API + '/importar', fd); aplica(j); toast(`${j.importados} pedidos importados${j.problemas.length ? ', ' + j.problemas.length + ' linha(s) com problema' : ''}. Toque ▶.`);
      if (j.problemas.length) alert('Linhas que ficaram de fora:\n' + j.problemas.join('\n')); } catch (er) { toast(er.message); }
    e.target.value = ''; });
  carregaCenarios();
}
$('#encerrar').addEventListener('click', () => { if (confirm('Encerrar a noite? Os pedidos saem da tela (baixe a planilha antes se quiser guardar).')) acao('limpar'); });

atualiza(); setInterval(atualiza, 2000); setInterval(() => E && desenha(), 1000);
"""


def pagina(espaco: str = "real") -> str:
    x0, y0, x1, y1 = recorte()
    w, h = x1 - x0, y1 - y0
    b64 = fundo_base64()
    img = (f'<image href="data:image/jpeg;base64,{b64}" width="{w}" height="{h}" opacity=".92"/>' if b64
           else f'<rect width="{w}" height="{h}" fill="var(--soft)"/>')
    proj = lambda la, lo: (_mundo(la, lo, FUNDO["z"])[0] - FUNDO["px0"] - x0, _mundo(la, lo, FUNDO["z"])[1] - FUNDO["py0"] - y0)
    lx, ly = proj(*itajuba.LOJA)
    rot = "".join(f'<text x="{proj(b[1], b[2])[0]:.0f}" y="{proj(b[1], b[2])[1] - 13:.0f}" text-anchor="middle" font-size="12" fill="#334" '
                  f'stroke="#fff" stroke-width="3" paint-order="stroke" opacity=".75">{html.escape(b[0])}</text>'
                  for b in itajuba.BAIRROS if b[3] >= 30)
    svg = (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Mapa de Itajubá com a loja, os pedidos e os motoboys">{img}{rot}'
           f'<g id="camada"></g><g><rect x="{lx - 15:.0f}" y="{ly - 15:.0f}" width="30" height="30" rx="7" fill="#141920" stroke="#fff" '
           f'stroke-width="3"/><text x="{lx:.0f}" y="{ly + 6:.0f}" text-anchor="middle" font-size="17" font-weight="900" fill="#fff">O</text>'
           f'<title>Empório Osório</title></g></svg>')
    pill = lambda nome, valor, rotulo, marcado=False: (f'<label><input type="radio" name="{nome}" value="{html.escape(valor)}"'
                                                        f'{" checked" if marcado else ""}><span>{rotulo}</span></label>')
    canais = "".join(pill("canal", c, f'<span class="tag" style="background:{cor}">{sig}</span>{html.escape(c.replace("iFood ", ""))}',
                          c == "iFood Burguer") for c, (sig, cor) in CANAL.items())
    tipos = "".join(pill("tipo", t, f"{EMOJI[t]} {CURTO[t]}", t == "lanche") for t in D.TIPOS)
    bairros = "".join(f"<option>{html.escape(b)}</option>" for b in sorted(D.BAIRROS))
    treino = espaco == "treino"
    vel_bts = "".join(f'<button type="button" data-v="{v}">{v}×</button>' for v in (1, 5, 10, 20))
    barra_treino = f"""<section class="card treino"><h2>Treino</h2>
<div class="linha"><select id="cenario" aria-label="Cenário"></select>
<label class="muted" style="font-size:13px">Motoboys <input id="cen-motos" class="num" type="number" min="1" max="10" value="3" style="width:64px;padding:6px 8px"></label>
<button class="bt prim" id="carregar" type="button">Começar este cenário</button>
<span class="muted">ou</span><label class="bt" for="arquivo" style="cursor:pointer">⬆ Importar planilha</label><input id="arquivo" type="file" accept=".xlsx,.csv" hidden>
<a class="bt" href="/api/despacho/modelo.xlsx">⬇ Modelo da planilha</a></div>
<p class="desc" id="cen-desc"></p>
<div class="linha" style="margin-top:10px"><button class="bt" id="tocar" type="button">▶ Tocar</button>
<span class="seg" id="vel">{vel_bts}</span>
<button class="bt" id="mais5" type="button">+5 min</button>
<label class="interruptor"><input type="checkbox" id="piloto"> Piloto automático <span class="muted" style="font-weight:400;font-size:13px">(o motoboy sai sozinho quando o robô manda)</span></label>
<button class="bt" id="inventado" type="button">+ Pedido inventado</button></div>
<div id="progresso" style="display:none"><div class="desc" id="prog-txt"></div><div class="barra"><i id="prog-barra" style="width:0"></i></div><div id="fora"></div></div>
</section>""" if treino else ""
    selo = '<span class="selo" id="selo-vel">treino</span>' if treino else '<span class="selo vivo">ao vivo</span>'
    aviso_vivo = ("" if treino else '<p class="dica" style="margin:0 0 12px">Pedidos de verdade. O endereço do cliente fica só '
                  'neste servidor e sai da tela quando a noite é encerrada.</p>')
    dados = {"%ESPACO%": json.dumps(espaco), "%CORES%": json.dumps(CORES_MOTO), "%CANAL%": json.dumps(CANAL, ensure_ascii=False),
             "%EMOJI%": json.dumps(EMOJI, ensure_ascii=False), "%CURTO%": json.dumps(CURTO, ensure_ascii=False),
             "%PADRAO%": json.dumps({"preparo": D.PREPARO_MIN, "prazo": D.PRAZO_MIN}, ensure_ascii=False),
             "%FUNDO%": json.dumps({"z": FUNDO["z"], "px0": FUNDO["px0"], "py0": FUNDO["py0"], "x0": x0, "y0": y0})}
    js = JS
    for k, v in dados.items():
        js = js.replace(k, v)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Despacho</title><style>{CSS}</style></head><body>
<header class="topo"><div class="in"><span class="marca">🛵 Despacho</span>
<nav class="modos" aria-label="Modo"><a href="/despacho/real" class="{'' if treino else 'on'}">Ao vivo</a><a href="/despacho/treino" class="{'on' if treino else ''}">Treino</a></nav>
<span class="relogio" id="relogio">··:··</span>{selo}
<div class="dir"><button class="ico" id="som" type="button">🔕 Som</button><a href="/rotas/">Tela de rotas</a><a href="/">Início</a><a href="/sair">Sair</a></div></div></header>
<main class="wrap">{aviso_vivo}{barra_treino}
<div class="kpis" id="kpis"></div>
<div class="grade"><div class="lado">
<section class="card"><h2>Chegou pedido</h2><form id="form" autocomplete="off">
<div class="pills" role="radiogroup" aria-label="Canal">{canais}</div>
<label class="rot" for="endereco">Endereço</label>
<div class="campo"><input id="endereco" name="endereco" type="text" placeholder="Rua e número, ou cole a localização do WhatsApp" aria-describedby="achado" maxlength="140">
<div class="sug" id="sug" role="listbox"></div></div><div class="achado" id="achado" aria-live="polite"></div>
<label class="rot" for="bairro">Bairro <span style="font-weight:400">(se não souber a rua)</span></label>
<div class="campo"><select id="bairro" name="bairro"><option value="">·</option>{bairros}</select></div>
<label class="rot">O que é</label><div class="pills" role="radiogroup" aria-label="Tipo">{tipos}</div>
<div class="tempos" style="margin-top:12px"><label>Número<input class="num" name="num" type="text" inputmode="numeric" maxlength="12" placeholder="4821"></label>
<label>Cozinha (min)<input class="num" name="preparo_min" type="number" min="0" max="120"></label>
<label>Prazo (min)<input class="num" name="prazo_min" type="number" min="5" max="180"></label></div>
<button class="bt prim" id="mandar" type="submit" style="width:100%;margin-top:14px;padding:12px;font-size:16px">Mandar para o robô ⏎</button></form>
<div class="resposta" id="resposta" aria-live="polite"></div>
<p class="dica">O robô manda um pedido por motoboy, junta dois só se ninguém estiver parado, nunca põe lanche com bebida grande e trata duas caixas de litrão como moto cheia. Você pode trocar o motoboy de qualquer pedido na lista.</p></section>
<section class="card"><h2>Motoboys no turno</h2><form id="form-moto" style="display:flex;gap:8px">
<input class="num" name="nome" type="text" placeholder="Primeiro nome" maxlength="20" aria-label="Nome do motoboy"><button class="bt" type="submit">Entrar no turno</button></form></section>
</div><div>
<section class="card"><h2>Motoboys</h2><div class="motos" id="motos"></div></section>
<section class="card"><div class="mapa">{svg}</div>
<div class="legenda"><span>○ na cozinha</span><span>● pronto</span><span>◉ na rua (borda na cor do motoboy)</span><span>· pontilhado: próxima saída</span><span>Mapa e ruas: OpenStreetMap</span></div></section>
<section class="card"><h2>Pedidos</h2><div class="rolar"><table><thead><tr><th>Pedido</th><th>O que é</th><th>Onde</th><th>Cozinha</th><th>Motoboy</th><th>Saída</th><th></th></tr></thead>
<tbody id="fila"></tbody></table></div></section>
<section class="card"><h2>Resultado da noite</h2><div class="fim" id="fim">🏁 Todos os pedidos do cenário foram entregues. Este é o resultado.</div>
<div class="res" id="resultado"></div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
<a class="bt" href="/api/despacho/{espaco}/exportar.xlsx">⬇ Baixar a noite (Excel)</a><button class="bt" id="encerrar" type="button">Encerrar a noite</button></div></section>
</div></div></main><div class="toast" id="toast" role="status"></div>
<script>{js}</script></body></html>"""
