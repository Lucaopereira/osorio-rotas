"""A página do simulador de rotas: o que a simulação mostra, a comparação e a noite minuto a minuto no mapa.

    python -m robo_rotas.simulador --pagina caminho.html
    python -m pipeline --rotas                      # grava simulador-de-rotas.html na pasta da reunião

Tudo é calculado na hora a partir de `simulador.py`: nenhum número desta página é digitado.
"""
from __future__ import annotations

import base64
import html
import io
import json
import math
import statistics
from pathlib import Path

from robo_rotas import itajuba, regras, simulador as S

DIAS = ("sexta", "sábado", "terça")
MOTOS = (2, 3, 4, 5, 6, 8)
NA_TABELA = ("um", "dois", "tres", "hoje")
CORES_MOTO = ["#2563eb", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#db2777", "#65a30d", "#78716c"]
CANAIS = ["iFood Burguer", "iFood Marmita", "Zé", "Site"]
TAMANHOS = ["lanche", "marmita"] + [t[0] for t in S.TAMANHO_ZE]
MARGEM_GRAU = 0.006


# ---------- o mapa ----------
def _mundo(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 256 * 2 ** z
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def _recorte():
    """O pedaço da imagem da tela que cobre a loja e os bairros, em pixels do zoom 14."""
    f = itajuba.FUNDO
    lats = [b[1] for b in itajuba.BAIRROS] + [itajuba.LOJA[0]]
    lons = [b[2] for b in itajuba.BAIRROS] + [itajuba.LOJA[1]]
    x0, y0 = _mundo(max(lats) + MARGEM_GRAU, min(lons) - MARGEM_GRAU, f["z"])
    x1, y1 = _mundo(min(lats) - MARGEM_GRAU, max(lons) + MARGEM_GRAU, f["z"])
    return int(x0 - f["px0"]), int(y0 - f["py0"]), int(x1 - f["px0"]), int(y1 - f["py0"])


def _fundo_base64() -> tuple[str, int, int] | None:
    caminho = Path(__file__).parent / "tela" / itajuba.FUNDO["arquivo"]
    try:
        from PIL import Image
    except ImportError:
        return None
    if not caminho.exists():
        return None
    x0, y0, x1, y1 = _recorte()
    img = Image.open(caminho).convert("RGB").crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, optimize=True)
    return base64.b64encode(buf.getvalue()).decode(), img.width, img.height


def _px(lat: float, lon: float) -> tuple[float, float]:
    f = itajuba.FUNDO
    x0, y0, _, _ = _recorte()
    x, y = _mundo(lat, lon, f["z"])
    return round(x - f["px0"] - x0, 1), round(y - f["py0"] - y0, 1)


# ---------- os números ----------
def _noite_compacta(noite: S.Noite) -> dict:
    """Uma noite no formato curto que o JavaScript da página lê."""
    motos = {m.nome: i for i, m in enumerate(noite.motos)}
    bairros = {b[0]: i for i, b in enumerate(itajuba.BAIRROS)}
    idx = {p.ref: i for i, p in enumerate(noite.pedidos)}
    r1 = lambda x: round(x, 1)
    peds = []
    for p in noite.pedidos:
        x, y = _px(p.lat, p.lon)
        sug = [[r1(t), motos[m] if m else -1] for t, m in p.sugestoes]
        peds.append([x, y, r1(p.criado), r1(p.pronto), r1(p.saiu), r1(p.chegou), CANAIS.index(p.canal),
                     bairros[p.bairro], p.num, r1(p.prazo), TAMANHOS.index(p.tamanho), motos[p.moto], sug])
    saidas = [[motos[s["moto"]], r1(s["sai"]), r1(s["volta"]), [idx[r] for r in s["refs"]]] for s in noite.saidas]
    return {"p": peds, "s": saidas, "n": len(noite.motos)}


def dados(ini: int = 18, fim: int = 25, noites: int = 10, dias=DIAS) -> dict:
    sementes = range(1, noites + 1)
    tabela, replays, medidos = {}, {}, {}
    for dia in dias:
        pols = tuple(S.POLITICAS) if dia == "sexta" else NA_TABELA
        res, lotes = S.cenarios(dia, ini, fim, MOTOS, sementes, pols)
        tabela[dia] = {f"{n}|{p}": r for (n, p), r in res.items()}
        tabela[dia]["_pedidos"] = statistics.mean(len(v) for v in lotes.values())
        for n in MOTOS:
            for p in NA_TABELA:
                replays[f"{dia}|{n}|{p}"] = _noite_compacta(S.simular(lotes[1], n, p, 1))
        if dia == "sexta":
            # conferência: o jeito de hoje simulado, do pedido pronto até a porta, contra o medido no Cardápio Web
            for n in (4, 5):
                v = []
                for s in sementes:
                    no = S.simular(lotes[s], n, "hoje", s)
                    v += [p.chegou - p.pronto for p in no.pedidos if p.canal.startswith("iFood")]
                v.sort()
                medidos[n] = (statistics.median(v), v[int(0.75 * (len(v) - 1))])
    return {"tabela": tabela, "replays": replays, "calibra": medidos, "ini": ini, "fim": fim, "noites": noites}


# ---------- texto ----------
def _n(x: float, casas: int = 0) -> str:
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return _n(x) + "%"


def _menor_que_basta(tab: dict, pol: str, limite: float = 5.0):
    for n in MOTOS:
        if tab[f"{n}|{pol}"]["pct_atrasado"] < limite:
            return n
    return None


def achados(D: dict) -> list[str]:
    sx = D["tabela"]["sexta"]
    g = lambda n, p, k: sx[f"{n}|{p}"][k]
    basta = {dia: _menor_que_basta(D["tabela"][dia], "dois") for dia in D["tabela"]}
    out = [
        f"<b>Com 4 motoboys numa sexta, as regras levam o pedido até a porta em {_n(g(4, 'dois', 'tempo_medio'))} min em média, "
        f"contra {_n(g(4, 'hoje', 'tempo_medio'))} min do jeito parecido com o de hoje.</b> Atrasados: "
        f"{_pct(g(4, 'dois', 'pct_atrasado'))} contra {_pct(g(4, 'hoje', 'pct_atrasado'))}. Comida fria: "
        f"{_pct(g(4, 'dois', 'pct_fria'))} contra {_pct(g(4, 'hoje', 'pct_fria'))}. A diferença é o motoboy não ficar "
        f"esperando juntar pedido na loja.",
        _aviso(g),
        f"<b>Até 2 ou até 3 por saída dá o mesmo resultado.</b> Com a regra dos 800 m, o terceiro pedido quase nunca "
        f"cabe: {_pct(g(4, 'tres', 'pct_tres_mais'))} dos pedidos saíram em trio com 4 motoboys. Fica a regra simples, "
        f"no máximo 2.",
        f"<b>Não misturar lanche com bebida grande não atrasa a entrega.</b> Liberando a mistura, com 4 motoboys, o tempo "
        f"médio fica em {_n(g(4, 'dois_mistura', 'tempo_medio'))} min e os atrasados em "
        f"{_pct(g(4, 'dois_mistura', 'pct_atrasado'))}: a regra protege o lanche sem custar tempo.",
    ]
    falta = (f"<b>Com motoboy de menos, as regras pioram e o jeito de hoje vira o menos ruim.</b> Com 3 motoboys numa sexta, "
             f"as regras deixam {_pct(g(3, 'dois', 'pct_atrasado'))} atrasado e juntar tudo como hoje, "
             f"{_pct(g(3, 'hoje', 'pct_atrasado'))}: levar mais pedidos por saída dá conta de mais pedidos, mesmo chegando "
             f"mais frio ({_pct(g(3, 'hoje', 'pct_fria'))} de comida fria). Com 2, nada resolve "
             f"({_pct(g(2, 'dois', 'pct_atrasado'))} e {_pct(g(2, 'hoje', 'pct_atrasado'))}). Falta uma decisão do Ricardo "
             f"para essa noite: liberar mais pedidos por saída, aumentar o prazo no aplicativo ou chamar mais um motoboy.")
    nomes = {"sexta": "na sexta", "sábado": "no sábado", "terça": "na terça"}
    falta += " O mínimo para ficar abaixo de 5% de atraso, nesta noite média: " + ", ".join(
        f"{basta[d]} {nomes[d]}" if basta[d] else f"mais de 8 {nomes[d]}" for d in D["tabela"]) + "."
    out.insert(1, falta)
    return out


def _aviso(g) -> str:
    solto_t, fixo_t = g(4, "dois_solto", "tempo_medio"), g(4, "dois", "tempo_medio")
    custo = (f"não custa tempo ({_n(fixo_t)} min contra {_n(solto_t)} min refazendo tudo)" if fixo_t - solto_t < 0.75 else
             f"custa {_n(fixo_t - solto_t, 1)} min a mais em média ({_n(fixo_t, 1)} contra {_n(solto_t, 1)} min refazendo tudo a cada "
             f"minuto, e {_pct(g(4, 'dois', 'pct_atrasado'))} contra {_pct(g(4, 'dois_solto', 'pct_atrasado'))} de atrasados)")
    return (f"<b>Dá para dizer o motoboy na hora que o pedido chega.</b> Com 4 motoboys, "
            f"{_pct(g(4, 'dois', 'pct_sugerido_na_chegada'))} dos pedidos já aparecem com o nome do motoboy no minuto em que "
            f"chegam (os outros ganham motoboy quando alguém sai da loja), e {_pct(g(4, 'dois', 'pct_manteve_sugestao'))} ficam "
            f"com esse motoboy até a porta. Manter a palavra {custo}. Sem isso, só "
            f"{_pct(g(4, 'dois_solto', 'pct_manteve_sugestao'))} dos pedidos ficariam com o primeiro motoboy avisado, e a loja "
            f"não teria como confiar no aviso.")


def _tabela_html(D: dict, dia: str) -> str:
    tab = D["tabela"][dia]
    cab = "".join(f"<th>{html.escape(S.POLITICAS[p][0])}</th>" for p in NA_TABELA)
    linhas = []
    for n in MOTOS:
        cel = []
        for p in NA_TABELA:
            r = tab[f"{n}|{p}"]
            cls = "ruim" if r["pct_atrasado"] >= 20 else ("medio" if r["pct_atrasado"] >= 5 else "bom")
            cel.append(f'<td class="{cls}"><b>{_n(r["tempo_medio"])} min</b><span>{_pct(r["pct_atrasado"])} atrasado · '
                       f'{_pct(r["pct_fria"])} fria</span></td>')
        linhas.append(f"<tr><th>{n} motoboys</th>{''.join(cel)}</tr>")
    return (f'<table class="comp" data-dia="{html.escape(dia)}"><thead><tr><th></th>{cab}</tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table>')


CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#141920;--muted:#5a6472;--line:#d8dde4;--soft:#eef1f4;--accent:#2563eb;
--bom:#dff2e6;--bom-ink:#17703f;--medio:#fbedd2;--medio-ink:#8a5a0b;--ruim:#fbe1e2;--ruim-ink:#b4232b;
--c0:#d0302f;--c1:#e06d0b;--c2:#d4a800;--c3:#6a2a9a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1216;--card:#181c22;--ink:#e8ecf1;--muted:#9aa4b1;
--line:#2b313a;--soft:#13171c;--accent:#7aa7ff;--bom:#16331f;--bom-ink:#5fd08f;--medio:#3a2c12;--medio-ink:#f0b75a;
--ruim:#3f1b1e;--ruim-ink:#ff7a80;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1216;--card:#181c22;--ink:#e8ecf1;--muted:#9aa4b1;--line:#2b313a;--soft:#13171c;
--accent:#7aa7ff;--bom:#16331f;--bom-ink:#5fd08f;--medio:#3a2c12;--medio-ink:#f0b75a;--ruim:#3f1b1e;--ruim-ink:#ff7a80;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em}h2{font-size:20px;margin:36px 0 10px}
.sub{color:var(--muted);margin:0 0 18px;max-width:820px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.achados{display:grid;gap:10px;padding:0;margin:0;list-style:none}.achados li{background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:12px 16px}
.calibra{color:var(--muted);font-size:14px;margin-top:10px}
.abas{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}.abas button,.ctl button,.ctl select{font:inherit;border:1px solid var(--line);
background:var(--card);color:var(--ink);border-radius:999px;padding:5px 14px;cursor:pointer}
.abas button[aria-pressed="true"]{background:var(--ink);color:var(--card);border-color:var(--ink)}
.rolar{overflow-x:auto}table.comp{border-collapse:separate;border-spacing:4px;width:100%;min-width:640px}
table.comp th{font-weight:600;text-align:left;font-size:14px;color:var(--muted);padding:4px 8px}
table.comp td{border-radius:8px;padding:8px 10px;vertical-align:top}table.comp td b{display:block;font-size:17px}
table.comp td span{font-size:12.5px}td.bom{background:var(--bom);color:var(--bom-ink)}td.medio{background:var(--medio);color:var(--medio-ink)}
td.ruim{background:var(--ruim);color:var(--ruim-ink)}
.ctl{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-bottom:12px}.ctl label{font-size:14px;color:var(--muted)}
.ctl select{border-radius:8px;padding:5px 8px}.ctl input[type=range]{flex:1;min-width:200px}
.relogio{font:700 26px/1 'Space Grotesk',Inter,sans-serif;font-variant-numeric:tabular-nums;min-width:84px}
.app{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,1fr);gap:14px}
@media (max-width:860px){.app{grid-template-columns:minmax(0,1fr)}}
.mapa{position:relative;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:var(--soft)}
.mapa svg{display:block;width:100%;height:auto}
.contas{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:10px}
.contas div{background:var(--soft);border-radius:8px;padding:6px 8px;font-size:12px;color:var(--muted)}
.contas b{display:block;font-size:19px;color:var(--ink);font-variant-numeric:tabular-nums}
.lado h3{font-size:14px;margin:12px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.motos div,.feed div{font-size:13.5px;padding:5px 0;border-bottom:1px solid var(--line)}.feed{max-height:300px;overflow:auto}
.bola{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.tag{display:inline-block;font-size:11px;font-weight:700;border-radius:5px;padding:0 5px;color:#fff;margin-right:4px}
.atr{color:var(--ruim-ink);font-weight:600}.ok{color:var(--bom-ink)}
.legenda{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12.5px;color:var(--muted);margin-top:8px}
ol.regras li,ul.sup li{margin:4px 0}.fonte{color:var(--muted);font-size:13px}
code{background:var(--soft);padding:1px 5px;border-radius:5px;font-size:13px}
"""

JS = r"""
const D = JSON.parse(document.getElementById('dados').textContent);
const CAN = [{r:'iF',c:'var(--c0)'},{r:'MA',c:'var(--c1)'},{r:'Zé',c:'var(--c2)'},{r:'SI',c:'var(--c3)'}];
const $ = (s) => document.querySelector(s);
const hm = (m) => { const t = Math.round(D.ini * 60 + m) % 1440; return String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(t % 60).padStart(2, '0'); };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let N = null, t = 0, fim = 1, tocando = false, ult = 0, vel = 4;

document.querySelectorAll('.abas button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.abas button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  document.querySelectorAll('table.comp').forEach((tb) => tb.hidden = tb.dataset.dia !== b.dataset.dia);
}));

function carrega() {
  N = D.replays[[$('#dia').value, $('#motos').value, $('#jeito').value].join('|')];
  fim = Math.ceil(Math.max(...N.p.map((p) => p[5])) + 10);
  $('#tempo').max = fim; if (t > fim) t = fim;
  desenha();
}

function posMoto(i) {
  for (const s of N.s) {
    if (s[0] !== i || t < s[1] || t >= s[2]) continue;
    let aqui = D.loja, t0 = s[1];
    for (const k of s[3]) {
      const p = N.p[k], alvo = [p[0], p[1]];
      if (t < p[5]) { const f = (t - t0) / Math.max(0.01, p[5] - t0); return {x: aqui[0] + (alvo[0] - aqui[0]) * f, y: aqui[1] + (alvo[1] - aqui[1]) * f, s}; }
      if (t < p[5] + 3) return {x: alvo[0], y: alvo[1], s};
      aqui = alvo; t0 = p[5] + 3;
    }
    const f = (t - t0) / Math.max(0.01, s[2] - t0);
    return {x: aqui[0] + (D.loja[0] - aqui[0]) * f, y: aqui[1] + (D.loja[1] - aqui[1]) * f, s};
  }
  return null;
}

function sugAgora(p) { let m = -1; for (const [tt, mm] of p[12]) { if (tt <= t) m = mm; } return m; }
const nome = (p) => `<span class="tag" style="background:${CAN[p[6]].c}">${CAN[p[6]].r}</span>${esc(p[8])} ${esc(D.bairros[p[7]])}`;

function desenha() {
  $('#relogio').textContent = hm(t); $('#tempo').value = t;
  const g = [];
  let coz = 0, esp = 0, rua = 0, ent = 0, atr = 0;
  N.p.forEach((p, k) => {
    if (t < p[2]) return;
    const cor = CAN[p[6]].c;
    if (t < p[3]) { coz++; g.push(`<circle cx="${p[0]}" cy="${p[1]}" r="6" fill="none" stroke="${cor}" stroke-width="2.5"/>`); }
    else if (t < p[4]) { esp++; const longa = t - p[3] > 10; g.push(`<circle cx="${p[0]}" cy="${p[1]}" r="${longa ? 8 : 6.5}" fill="${cor}" stroke="${longa ? 'var(--ruim-ink)' : '#fff'}" stroke-width="2"/>`); }
    else if (t < p[5]) { rua++; g.push(`<circle cx="${p[0]}" cy="${p[1]}" r="6.5" fill="${cor}" stroke="${D.cores[p[11]]}" stroke-width="3"/>`); }
    else { ent++; if (p[5] > p[9]) atr++; if (t - p[5] < 20) g.push(`<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="${p[5] > p[9] ? 'var(--ruim-ink)' : 'var(--muted)'}" opacity=".55"/>`); }
  });
  const motos = [], linhas = [];
  for (let i = 0; i < N.n; i++) {
    const m = posMoto(i), cor = D.cores[i];
    if (m) {
      const falta = m.s[3].map((k) => N.p[k]).filter((p) => t < p[5]);
      let px = m.x, py = m.y;
      for (const p of falta) { linhas.push(`<line x1="${px}" y1="${py}" x2="${p[0]}" y2="${p[1]}" stroke="${cor}" stroke-width="2.5" stroke-dasharray="6 5"/>`); px = p[0]; py = p[1]; }
      motos.push(`<g><circle cx="${m.x}" cy="${m.y}" r="11" fill="${cor}" stroke="#fff" stroke-width="2.5"/><text x="${m.x}" y="${m.y + 4.5}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">${i + 1}</text></g>`);
    }
  }
  $('#camada').innerHTML = linhas.join('') + g.join('') + motos.join('');
  $('#c-coz').textContent = coz; $('#c-esp').textContent = esp; $('#c-rua').textContent = rua; $('#c-ent').textContent = ent; $('#c-atr').textContent = atr;

  const lista = [];
  for (let i = 0; i < N.n; i++) {
    const m = posMoto(i), bola = `<span class="bola" style="background:${D.cores[i]}"></span><b>Moto ${i + 1}</b> `;
    if (m) {
      const falta = m.s[3].map((k) => N.p[k]).filter((p) => t < p[5]);
      lista.push(falta.length ? `<div>${bola}na rua levando ${falta.map(nome).join(', ')}, volta ${hm(m.s[2])}</div>`
                              : `<div>${bola}entregou, voltando para a loja, chega ${hm(m.s[2])}</div>`);
    }
    else {
      const meus = N.p.filter((p) => t >= p[2] && t < p[4] && sugAgora(p) === i);
      lista.push(`<div>${bola}na loja${meus.length ? ', vai levar ' + meus.map((p) => nome(p) + (t < p[3] ? ' (na cozinha)' : ' (pronto)')).join(', ') : ', livre'}</div>`);
    }
  }
  $('#motos-lista').innerHTML = lista.join('');

  const ev = [];
  N.p.forEach((p) => {
    if (p[2] <= t) {
      const s0 = p[12].find((x) => x[0] - p[2] < 1);
      const txt = $('#jeito').value === 'hoje' ? 'sem aviso: espera alguém juntar' : (s0 && s0[1] >= 0 ? `o robô avisa a <b>Moto ${s0[1] + 1}</b>` : 'todos com saída marcada: espera o primeiro que sair');
      ev.push([p[2], `${hm(p[2])} chegou ${nome(p)} (${esc(D.tamanhos[p[10]])}): ${txt}`]);
    }
    if (p[5] <= t) {
      const tot = Math.round(p[5] - p[2]), at = p[5] > p[9];
      ev.push([p[5], `${hm(p[5])} entregue ${nome(p)} em ${tot} min, <span class="${at ? 'atr' : 'ok'}">${at ? 'atrasado ' + Math.round(p[5] - p[9]) + ' min' : 'no prazo'}</span>`]);
    }
  });
  N.s.forEach((s) => { if (s[1] <= t) ev.push([s[1] + 0.01, `${hm(s[1])} <b>Moto ${s[0] + 1}</b> saiu com ${s[3].length} pedido${s[3].length > 1 ? 's' : ''}: ${s[3].map((k) => nome(N.p[k])).join(' + ')}`]); });
  ev.sort((a, b) => b[0] - a[0]);
  $('#feed').innerHTML = ev.slice(0, 40).map((e) => `<div>${e[1]}</div>`).join('') || '<div>A noite ainda não começou.</div>';
}

let relogio = null;
function passo() {
  const agora = performance.now();
  t = Math.min(fim, t + (agora - ult) / 1000 * vel); ult = agora; desenha();
  if (t >= fim) para();
}
function para() { tocando = false; clearInterval(relogio); $('#play').textContent = 'Tocar'; }
$('#play').addEventListener('click', () => {
  if (tocando) return para();
  tocando = true; $('#play').textContent = 'Pausar';
  if (t >= fim) t = 0;
  ult = performance.now(); relogio = setInterval(passo, 80);
});
$('#vel').addEventListener('change', (e) => { vel = +e.target.value; });
$('#tempo').addEventListener('input', (e) => { t = +e.target.value; desenha(); });
['#dia', '#motos', '#jeito'].forEach((s) => $(s).addEventListener('change', carrega));
t = 120; carrega();
"""


def pagina(D: dict) -> str:
    fundo = _fundo_base64()
    x0, y0, x1, y1 = _recorte()
    w, h = x1 - x0, y1 - y0
    loja = _px(*itajuba.LOJA)
    sx = D["tabela"]["sexta"]
    ped_sexta = sx["_pedidos"]
    img = (f'<image href="data:image/jpeg;base64,{fundo[0]}" x="0" y="0" width="{w}" height="{h}" opacity=".9"/>'
           if fundo else f'<rect width="{w}" height="{h}" fill="var(--soft)"/>')
    rot_bairros = "".join(
        f'<text x="{_px(b[1], b[2])[0]}" y="{_px(b[1], b[2])[1] - 9}" text-anchor="middle" font-size="11" fill="#334" '
        f'stroke="#fff" stroke-width="3" paint-order="stroke" opacity=".75">{html.escape(b[0])}</text>'
        for b in itajuba.BAIRROS if b[3] >= 30)
    svg = (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Mapa de Itajubá com a loja, os pedidos e os motoboys">{img}'
           f'{rot_bairros}<g id="camada"></g>'
           f'<g><rect x="{loja[0] - 13}" y="{loja[1] - 13}" width="26" height="26" rx="6" fill="#141920" stroke="#fff" stroke-width="2.5"/>'
           f'<text x="{loja[0]}" y="{loja[1] + 5}" text-anchor="middle" font-size="14" font-weight="800" fill="#fff">O</text></g></svg>')
    js_dados = {"replays": D["replays"], "ini": D["ini"], "loja": list(loja), "cores": CORES_MOTO,
                "bairros": [b[0] for b in itajuba.BAIRROS], "tamanhos": TAMANHOS}
    cal = D["calibra"]
    med, p75 = itajuba.MEDIDO_PRONTO_PORTA
    calibra = (f"Conferência da velocidade: no jeito parecido com o de hoje, o pedido do iFood leva {_n(cal[4][0])} min do pronto "
               f"até a porta (mediana) com 4 motoboys e {_n(cal[4][1])} min em 3 de cada 4. O medido no Cardápio Web, de 03/10 "
               f"a 08/11, é {med} e {p75} min. O simulador anda perto do real.")
    achs = "".join(f"<li>{a}</li>" for a in achados(D))
    abas = "".join(f'<button type="button" data-dia="{d}" aria-pressed="{str(d == "sexta").lower()}">{d.capitalize()}</button>'
                   for d in D["tabela"])
    tabelas = "".join(_tabela_html(D, d).replace("<table", "<table hidden" if d != "sexta" else "<table", 1) for d in D["tabela"])
    opc = lambda vals, sel, rot=str: "".join(f'<option value="{v}"{" selected" if v == sel else ""}>{html.escape(rot(v))}</option>' for v in vals)
    pedidos_hora = itajuba.PEDIDOS_HORA["sexta"]
    pico = max(S.horas(D["ini"], D["fim"]), key=lambda h: pedidos_hora.get(h, 0))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Simulador de rotas</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Simulador de rotas do Osório</h1>
<p class="sub">Uma noite inventada em Itajubá, das {D['ini']}h à {D['fim'] % 24}h, saindo da loja ({html.escape(itajuba.LOJA_ENDERECO)}).
Os pedidos chegam no mesmo ritmo das entregas de verdade de 05/10 a 08/11 (numa sexta, ~{_n(ped_sexta)} entregas, pico de
{_n(pedidos_hora[pico], 1)} por hora às {pico}h), o bairro é sorteado pela frequência real de entrega, e o endereço é um ponto
inventado dentro do bairro. Nenhum pedido aqui é de cliente. O robô decide a cada minuto com as regras da reunião de 12/11,
a mesma conta que vai rodar no servidor. Os números da comparação são a média de {D['noites']} noites sorteadas.</p>

<h2>O que a simulação mostra</h2>
<ul class="achados">{achs}</ul>
<p class="calibra">{calibra}</p>

<h2>Quantos motoboys e qual regra</h2>
<p class="sub">Tempo médio do pedido até a porta, e quantos chegam atrasados e com a comida fria (mais de {S.FRIA_MIN} min
entre ficar pronta e chegar). Verde: menos de 5% atrasado. Vermelho: 20% ou mais.</p>
<div class="abas">{abas}</div>
<div class="card rolar">{tabelas}</div>

<h2>A noite, minuto a minuto</h2>
<p class="sub">Escolha o dia, quantos motoboys e o jeito de despachar, e toque. Cada pedido aparece no mapa quando chega
(aro: na cozinha; cheio: pronto esperando, com borda vermelha se espera mais de 10 min; com a cor do motoboy em volta: na rua).
Ao lado, o que o robô avisa na hora que o pedido chega.</p>
<div class="card">
<div class="ctl">
<label>Dia <select id="dia">{opc(D['tabela'].keys(), 'sexta', str.capitalize)}</select></label>
<label>Motoboys <select id="motos">{opc(MOTOS, 4)}</select></label>
<label>Jeito <select id="jeito">{opc(NA_TABELA, 'dois', lambda p: S.POLITICAS[p][0])}</select></label>
<button id="play" type="button">Tocar</button>
<label>Velocidade <select id="vel"><option value="2">2 min/s</option><option value="4" selected>4 min/s</option><option value="10">10 min/s</option></select></label>
</div>
<div class="ctl"><span class="relogio" id="relogio">18:00</span><input id="tempo" type="range" min="0" max="420" step="0.5" value="0" aria-label="Hora da noite"></div>
<div class="app">
<div><div class="mapa">{svg}</div>
<div class="legenda"><span><span class="tag" style="background:var(--c0)">iF</span>iFood Burguer</span><span><span class="tag" style="background:var(--c1)">MA</span>Marmita</span>
<span><span class="tag" style="background:var(--c2)">Zé</span>Zé Delivery</span><span><span class="tag" style="background:var(--c3)">SI</span>Site</span>
<span>O quadrado preto é a loja.</span><span>Fundo: OpenStreetMap.</span></div></div>
<div class="lado">
<div class="contas"><div><b id="c-coz">0</b>na cozinha</div><div><b id="c-esp">0</b>prontos</div><div><b id="c-rua">0</b>na rua</div><div><b id="c-ent">0</b>entregues</div><div><b id="c-atr">0</b>atrasados</div></div>
<h3>Motoboys</h3><div class="motos" id="motos-lista"></div>
<h3>O que aconteceu</h3><div class="feed" id="feed"></div>
</div></div></div>

<h2>As regras, como foram ditas</h2>
<div class="card"><ol class="regras">
<li>Um pedido por motoboy. <span class="fonte">Reunião de 12/11, 27:03 e 44:04</span></li>
<li>Dois só se não houver motoboy parado, ou se o pedido ia esperar mais de {regras.ESPERA_MAX} min pronto na loja. <span class="fonte">44:04</span></li>
<li>Três só em último caso, com as paradas a até {_n(regras.PERTO_KM * 1000)} m uma da outra, "senão o terceiro chega frio ou atrasado". <span class="fonte">44:04</span>
Nesta página o jeito "Regras, até 2" não deixa sair com três.</li>
<li>Não misturar lanche com bebida. Bebida pequena (poucas latas) pode ir em cima da bag, como a tela de rotas já faz. <span class="fonte">43:18</span></li>
<li>Peso: duas caixas de litrão enchem a moto, não vai mais nada. <span class="fonte">44:04</span></li>
<li>Quantos motoboys tem no turno muda a conta: "hoje quatro, amanhã dois". <span class="fonte">43:18</span></li>
<li>Juntar não pode atrasar o pedido que já estava na saída, nem fazer ele chegar mais de {regras.PIORA_MAX} min depois.</li>
<li>O motoboy avisado quando o pedido chega fica com ele. Só troca se o pedido já está pronto, o motoboy dele está na rua e tem outro parado na loja sem nada.</li>
</ol>
<p class="fonte">O robô decide com o centro do bairro, nunca com o endereço do cliente, como na tela de rotas. Quem põe o pedido na bag continua sendo a loja.</p></div>

<h2>O que é suposição</h2>
<div class="card"><ul class="sup">
<li>Endereços inventados: até ~{_n(S.ESPALHA_KM * 1000)} m em volta do centro do bairro. A rua é a linha reta vezes {_n(regras.FATOR_RUA, 2)}, a moto anda a {_n(regras.VEL_KMH)} km/h, cada trecho varia {_n(S.TRANSITO * 100)}% para mais ou para menos, e o motoboy fica {regras.PARADA_MIN} min em cada porta.</li>
<li>Preparo: cozinha {S.PREPARO_COZINHA[0]} min em média (medido no Cardápio Web), bebida do Zé {S.PREPARO_ZE[0]} min (suposição).</li>
<li>Prazo até a porta: iFood {S.PRAZO['iFood Burguer']} min, Zé {S.PRAZO['Zé']} min, site {S.PRAZO['Site']} min (suposição: conferir o prazo que cada plataforma mostra ao cliente).</li>
<li>Tamanho do pedido do Zé: poucas latas 15%, fardo ou garrafas 50%, uma caixa de litrão 25%, duas caixas 10% (suposição).</li>
<li>"Parecido com hoje": o motoboy espera juntar e sai quando o pedido pronto mais antigo espera {S.HOJE_ESPERA} min ou com {S.HOJE_MAX} pedidos, misturando lanche e bebida. É o que o Ricardo descreveu ("cada motoboy sai com quatro, cinco pedidos"), não uma medida.</li>
<li>O WhatsApp não está em base nenhuma: o número real de entregas é maior.</li>
<li>A loja é um ponto aproximado na rua (o mapa não tem o número 596): trocar pelo ponto da tela de rotas.</li>
</ul></div>
<p class="fonte" style="margin-top:20px">Para rodar de novo: <code>python -m robo_rotas.simulador --pagina simulador-de-rotas.html</code>.
Uma noite no terminal: <code>python -m robo_rotas.simulador --dia sábado --motoboys 3</code>.</p>
</div>
<script type="application/json" id="dados">{json.dumps(js_dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")}</script>
<script>{JS}</script></body></html>"""


def gravar(caminho, **kw) -> Path:
    D = dados(**kw)
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pagina(D), encoding="utf-8")
    return p
