// Ponte entre a tela Waisorio e o servidor da VPS (robo_rotas/servidor.py).
// No claude.ai a tela chama claude.use("db") e recebe o banco do artefato. Aqui a mesma chamada recebe um objeto
// com as mesmas funções que a tela usa, e por trás dele está este servidor. A tela não muda uma linha.
(() => {
  "use strict";
  let estado = null, versao = 0, caiu = false;
  const ouvintes = new Set();

  const avisa = () => ouvintes.forEach((o) => { try { o.ok(); } catch (e) { console.error(e); } });
  const avisaErro = () => ouvintes.forEach((o) => { try { o.erro && o.erro({code: "unavailable"}); } catch (e) { console.error(e); } });

  async function laco() {
    for (;;) {
      try {
        const r = await fetch("/api/estado?v=" + versao, {credentials: "same-origin", cache: "no-store"});
        if (r.status === 401) { location.href = "/"; return; }
        if (!r.ok) throw new Error("http " + r.status);
        const novo = await r.json();
        const mudou = !estado || novo.v !== versao || caiu;
        estado = novo; versao = novo.v; caiu = false;
        if (mudou) avisa();
      } catch (e) {
        if (!caiu) { caiu = true; avisaErro(); }
        await new Promise((ok) => setTimeout(ok, 3000));
      }
    }
  }

  const docs = (col) => (estado && estado.colecoes[col]) || [];
  const instantaneo = (d) => ({id: d.id, exists: true, data: () => d.dados});

  async function pede(metodo, url, corpo) {
    const r = await fetch(url, {method: metodo, credentials: "same-origin", headers: {"Content-Type": "application/json"},
      body: corpo === undefined ? undefined : JSON.stringify(corpo)});
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { const e = new Error("sessão"); e.code = "not_granted"; throw e; }
    if (!r.ok) { const e = new Error(j.code || r.status); e.code = r.status === 403 ? "permission_denied" : (j.code || "erro"); throw e; }
    return j;
  }

  function assina(ok, erro) {
    const o = {ok, erro};
    ouvintes.add(o);
    if (estado) setTimeout(ok, 0);
    return () => ouvintes.delete(o);
  }

  function docRef(col, id) {
    const url = "/api/" + encodeURIComponent(col) + "/" + encodeURIComponent(id);
    const snap = () => {
      const d = docs(col).find((x) => x.id === id);
      return d ? {...instantaneo(d), metadata: {fromCache: false}} : {id, exists: false, data: () => undefined, metadata: {fromCache: false}};
    };
    return {
      id,
      get: async () => snap(),
      set: (dados) => pede("PUT", url, dados),
      update: () => Promise.reject(Object.assign(new Error("não usado pela tela"), {code: "unsupported"})),
      delete: () => pede("DELETE", url),
      onSnapshot: (cb, erro) => assina(() => cb(snap()), erro),
    };
  }

  function colRef(col, q = {}) {
    const lista = () => {
      let l = docs(col).slice();
      if (q.ordem) {
        const [campo, dir] = q.ordem, s = dir === "desc" ? -1 : 1;
        l.sort((a, b) => {
          const x = (a.dados || {})[campo], y = (b.dados || {})[campo];
          return x === y ? 0 : (x > y ? s : -s);
        });
      }
      if (q.limite) l = l.slice(0, q.limite);
      const d = l.map(instantaneo);
      return {docs: d, size: d.length, empty: !d.length, metadata: {fromCache: false}};
    };
    return {
      orderBy: (campo, dir = "asc") => colRef(col, {...q, ordem: [campo, dir]}),
      limit: (n) => colRef(col, {...q, limite: n}),
      doc: (id) => docRef(col, id),
      add: async (dados) => docRef(col, (await pede("POST", "/api/" + encodeURIComponent(col), dados)).id),
      get: async () => lista(),
      onSnapshot: (cb, erro) => assina(() => cb(lista()), erro),
    };
  }

  const db = Object.freeze({
    doc: (caminho) => { const [col, id] = String(caminho).split("/"); return docRef(col, id); },
    collection: (col) => colRef(String(col)),
  });

  let iniciado = false;
  window.claude = Object.freeze({
    use: async (nome) => {
      if (nome !== "db") return null;
      if (!iniciado) { iniciado = true; laco(); }
      return db;
    },
  });
})();
