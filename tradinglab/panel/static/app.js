"use strict";

// ---------------------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const DIA_MS = 86400000;
const estado = { series: [], estrategias: [], config: null, graficas: [], graficasPapel: [], papelActiva: null };

function esc(texto) {
  return String(texto).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function pct(x, signo = true) {
  if (x === null || x === undefined) return "-";
  const texto = (x * 100).toFixed(1) + "%";
  return signo && x > 0.0005 ? "+" + texto : texto;
}

const usd = (x) => (x === null || x === undefined ? "-" : x.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const entero = (x) => (x === null || x === undefined ? "-" : x.toLocaleString("es-MX"));
const fecha = (ms) => new Date(ms).toISOString().slice(0, 16).replace("T", " ");
const dia = (ms) => new Date(ms).toISOString().slice(0, 10);
const clase = (x) => (x > 0.0005 ? "positivo" : x < -0.0005 ? "negativo" : "");
const siNo = (v) => (v ? "SÍ" : "no");

function textoParametros(p) {
  return Object.keys(p).sort().map((k) => `${k}=${p[k]}`).join(" ");
}

async function api(ruta) {
  const respuesta = await fetch(ruta);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.detail || `Error ${respuesta.status}`);
  return datos;
}

function tabla(encabezados, filas) {
  const cabeza = "<thead><tr>" + encabezados.map((e) => `<th>${esc(e)}</th>`).join("") + "</tr></thead>";
  return cabeza + "<tbody>" + filas.join("") + "</tbody>";
}

// ---------------------------------------------------------------------------------------
// Pestañas
// ---------------------------------------------------------------------------------------

document.querySelectorAll(".pestana").forEach((b) => b.addEventListener("click", () => mostrarVista(b.dataset.vista)));

function mostrarVista(nombre, conHash = true) {
  if (conHash) history.replaceState(null, "", nombre === "backtest" ? location.pathname : "#" + nombre);
  document.querySelectorAll(".pestana").forEach((b) => b.classList.toggle("activa", b.dataset.vista === nombre));
  document.querySelectorAll(".vista").forEach((v) => v.classList.toggle("activa", v.id === "vista-" + nombre));
  if (nombre === "estudios") cargarEstudios();
  if (nombre === "papel") cargarPapel();
}

// ---------------------------------------------------------------------------------------
// Gráficas (TradingView Lightweight Charts 4.2)
// ---------------------------------------------------------------------------------------

const OPCIONES_GRAFICA = {
  autoSize: true,
  layout: { background: { color: "#120e1c" }, textColor: "#cfc6de", fontFamily: "Segoe UI, system-ui, sans-serif" },
  grid: { vertLines: { color: "#221a33" }, horzLines: { color: "#221a33" } },
  rightPriceScale: { borderColor: "#2e2442" },
  // minBarSpacing bajo: permite ver años de velas completos en pantalla.
  timeScale: { borderColor: "#2e2442", timeVisible: true, secondsVisible: false, minBarSpacing: 0.001 },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
};
const COLOR_ESTRATEGIA = "#b388ff";
const COLOR_BH = "#f0b429";
const VELAS_INICIALES = 1500;

function crearGrafica(id) {
  const contenedor = $(id);
  contenedor.innerHTML = "";
  return LightweightCharts.createChart(contenedor, OPCIONES_GRAFICA);
}

function sincronizar(graficas) {
  let ocupado = false;
  graficas.forEach((g) =>
    g.timeScale().subscribeVisibleLogicalRangeChange((rango) => {
      if (ocupado || !rango) return;
      ocupado = true;
      graficas.forEach((otra) => otra !== g && otra.timeScale().setVisibleLogicalRange(rango));
      ocupado = false;
    })
  );
}

function marcadores(marcas) {
  return marcas.map((m) =>
    m.lado === "compra"
      ? { time: m.time, position: "belowBar", color: "#42a5f5", shape: "arrowUp" }
      : { time: m.time, position: "aboveBar", color: m.motivo === "fin de ventana" ? "#9a90ad" : "#ff4081", shape: "arrowDown" }
  );
}

function seriesVelas(grafica) {
  return grafica.addCandlestickSeries({
    upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350",
  });
}

// ---------------------------------------------------------------------------------------
// Backtest
// ---------------------------------------------------------------------------------------

async function iniciar() {
  try {
    const [series, estrategias, config] = await Promise.all([api("/api/series"), api("/api/estrategias"), api("/api/configuracion")]);
    estado.series = series;
    estado.estrategias = estrategias;
    estado.config = config;
  } catch (error) {
    $("mensaje").textContent = error.message;
    return;
  }
  const simbolos = [...new Set(estado.series.map((s) => s.simbolo))].sort();
  const intervalos = [...new Set(estado.series.map((s) => s.intervalo))];
  $("f-simbolo").innerHTML = simbolos.map((s) => `<option>${esc(s)}</option>`).join("");
  $("f-intervalo").innerHTML = intervalos.map((i) => `<option ${i === "1h" ? "selected" : ""}>${esc(i)}</option>`).join("");
  $("f-estrategia").innerHTML = estado.estrategias.map((e) => `<option value="${esc(e.nombre)}">${esc(e.titulo)}</option>`).join("");
  $("f-capital").placeholder = estado.config.capital_inicial;
  $("f-estrategia").addEventListener("change", () => mostrarParametros());
  $("f-intervalo").addEventListener("change", ajustarFechas);
  $("f-simbolo").addEventListener("change", ajustarFechas);
  $("formulario").addEventListener("submit", (ev) => {
    ev.preventDefault();
    simular();
  });
  mostrarParametros();
  simular();
  // La dirección puede abrir otra pestaña: #estudios, #estudios/2 o #papel.
  const [vista, id] = location.hash.slice(1).split("/");
  if (vista === "estudios" || vista === "papel") {
    mostrarVista(vista, false);
    if (vista === "estudios" && id) verEstudio(Number(id));
    if (vista === "papel" && id) {
      estado.papelActiva = decodeURIComponent(id);
      cargarPapel();
    }
  }
}

function estrategiaActual() {
  return estado.estrategias.find((e) => e.nombre === $("f-estrategia").value);
}

function mostrarParametros(valores) {
  const e = estrategiaActual();
  $("f-parametros").innerHTML = e.parametros
    .map((p) => {
      const valor = valores && valores[p.nombre] !== undefined ? valores[p.nombre] : p.por_defecto;
      const paso = p.tipo === "int" ? "1" : "any";
      return `<label title="${esc(p.descripcion)}">${esc(p.nombre)}<input data-param="${esc(p.nombre)}" type="number" step="${paso}" value="${esc(valor)}"></label>`;
    })
    .join("");
  $("descripcion").textContent = e.descripcion;
}

function serieActual() {
  return estado.series.find((s) => s.simbolo === $("f-simbolo").value && s.intervalo === $("f-intervalo").value);
}

function ajustarFechas() {
  // Una serie de 5m completa no cabe en el navegador: se propone el último año.
  const s = serieActual();
  if (!s || $("f-desde").value) return;
  const duracion = (s.hasta_ms - s.desde_ms) / Math.max(s.velas - 1, 1);
  if (s.velas > estado.config.max_velas) $("f-desde").value = dia(s.hasta_ms - 365 * DIA_MS + duracion);
}

async function simular() {
  const parametros = {};
  document.querySelectorAll("[data-param]").forEach((i) => (parametros[i.dataset.param] = i.value));
  const consulta = new URLSearchParams({
    simbolo: $("f-simbolo").value,
    intervalo: $("f-intervalo").value,
    estrategia: $("f-estrategia").value,
    parametros: JSON.stringify(parametros),
    fraccion: $("f-fraccion").value || "1",
  });
  if ($("f-desde").value) consulta.set("desde", $("f-desde").value);
  if ($("f-hasta").value) consulta.set("hasta", $("f-hasta").value);
  if ($("f-capital").value) consulta.set("capital", $("f-capital").value);

  $("f-simular").disabled = true;
  $("mensaje").textContent = "Simulando...";
  try {
    const d = await api("/api/backtest?" + consulta);
    $("mensaje").textContent = "";
    $("resultado").classList.remove("oculto");
    dibujarBacktest(d);
  } catch (error) {
    $("mensaje").textContent = error.message;
  } finally {
    $("f-simular").disabled = false;
  }
}

function dibujarBacktest(d) {
  const m = d.metricas;
  const bh = d.referencias.comprar_y_mantener;
  const nada = d.referencias.no_operar;
  const gana = d.le_gana_a_no_operar && d.le_gana_a_comprar_y_mantener;
  $("veredicto").className = "veredicto " + (gana ? "gana" : "pierde");
  $("veredicto").textContent =
    `¿Le gana a no operar? ${siNo(d.le_gana_a_no_operar)} · ¿Le gana a comprar y mantener? ${siNo(d.le_gana_a_comprar_y_mantener)} · ` +
    "Un solo backtest dentro de muestra no es evidencia: la evidencia sale del walk-forward.";

  const filas = [
    ["Rendimiento neto", (x) => pct(x.rendimiento), true],
    ["Capital final (USDT)", (x) => usd(x.capital_final)],
    ["Drawdown máximo", (x) => pct(x.drawdown_maximo)],
    ["Operaciones", (x) => entero(x.operaciones)],
    ["Comisiones pagadas (USDT)", (x) => usd(x.comisiones)],
    ["Costo del deslizamiento (USDT)", (x) => usd(x.costo_deslizamiento)],
    ["Operaciones ganadoras", (x) => pct(x.ganadoras, false)],
    ["Tiempo dentro del mercado", (x) => pct(x.exposicion, false)],
  ].map(([nombre, f, color]) => `<tr><td>${nombre}</td>` + [m, bh, nada].map((x) => `<td class="${color ? clase(x.rendimiento) : ""}">${f(x)}</td>`).join("") + "</tr>");
  $("metricas").innerHTML = tabla(["", "Estrategia", "Comprar y mantener", "No operar"], filas);
  $("texto-costos").textContent = `comisión ${(d.costos.comision * 100).toFixed(2)}% y deslizamiento ${(d.costos.deslizamiento * 100).toFixed(2)}% por lado`;

  estado.graficas.forEach((g) => g.remove());
  const gVelas = crearGrafica("grafica-velas");
  const velas = seriesVelas(gVelas);
  velas.setData(d.velas);
  velas.setMarkers(marcadores(d.marcas));

  const gCapital = crearGrafica("grafica-capital");
  // Escala logarítmica: con rendimientos tan distintos, la lineal aplasta una de las curvas.
  gCapital.priceScale("right").applyOptions({ mode: LightweightCharts.PriceScaleMode.Logarithmic });
  gCapital.addLineSeries({ color: COLOR_BH, lineWidth: 1, priceLineVisible: false }).setData(d.capital_bh);
  gCapital.addLineSeries({ color: COLOR_ESTRATEGIA, lineWidth: 2, priceLineVisible: false }).setData(d.capital);

  const gDrawdown = crearGrafica("grafica-drawdown");
  gDrawdown.addLineSeries({ color: COLOR_BH, lineWidth: 1, priceLineVisible: false }).setData(d.drawdown_bh);
  gDrawdown
    .addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: COLOR_ESTRATEGIA, bottomLineColor: COLOR_ESTRATEGIA,
      bottomFillColor1: "rgba(179,136,255,0.05)", bottomFillColor2: "rgba(179,136,255,0.35)",
      lineWidth: 2, priceLineVisible: false,
    })
    .setData(d.drawdown);

  estado.graficas = [gVelas, gCapital, gDrawdown];
  // Con muchas operaciones las marcas tapan las velas: se empieza mostrando solo el final.
  const n = d.velas.length;
  const recortar = d.marcas.length > 300 && n > VELAS_INICIALES;
  estado.graficas.forEach((g) =>
    recortar ? g.timeScale().setVisibleLogicalRange({ from: n - VELAS_INICIALES, to: n + 3 }) : g.timeScale().fitContent()
  );
  $("texto-zoom").textContent = recortar
    ? ` · se muestran las últimas ${entero(VELAS_INICIALES)} velas: aleja con la rueda del ratón para ver todo`
    : "";
  sincronizar(estado.graficas);

  const ultimas = d.operaciones.slice(-500).reverse();
  $("texto-operaciones").textContent =
    d.operaciones.length > 500 ? `las 500 más recientes de ${entero(d.operaciones.length)}` : `${entero(d.operaciones.length)} en total`;
  $("operaciones").innerHTML = tabla(
    ["Entrada (UTC)", "Salida (UTC)", "Precio entrada", "Precio salida", "Ganancia USDT", "Rendimiento"],
    ultimas.map(
      (o) => `<tr><td>${fecha(o.entrada)}</td><td>${fecha(o.salida)}</td><td>${o.precio_entrada.toLocaleString("es-MX")}</td>` +
        `<td>${o.precio_salida.toLocaleString("es-MX")}</td><td class="${clase(o.ganancia)}">${usd(o.ganancia)}</td>` +
        `<td class="${clase(o.rendimiento)}">${pct(o.rendimiento)}</td></tr>`
    )
  );
}

function abrirEnBacktest(corrida) {
  $("f-simbolo").value = corrida.simbolo;
  $("f-intervalo").value = corrida.intervalo;
  $("f-estrategia").value = corrida.estrategia;
  mostrarParametros(corrida.parametros);
  $("f-desde").value = dia(corrida.desde_ms);
  const s = serieActual();
  const final = s ? s.hasta_ms : Infinity;
  // "hasta" es exclusivo y por días: se redondea hacia arriba, o se deja vacío si llega al final de los datos.
  $("f-hasta").value = corrida.hasta_ms > final ? "" : dia(Math.ceil(corrida.hasta_ms / DIA_MS) * DIA_MS);
  mostrarVista("backtest");
  simular();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------------------------------------------------------------------------------------
// Estudios
// ---------------------------------------------------------------------------------------

async function cargarEstudios() {
  let estudios;
  try {
    estudios = await api("/api/estudios");
  } catch (error) {
    $("lista-estudios").innerHTML = `<tr><td>${esc(error.message)}</td></tr>`;
    return;
  }
  if (!estudios.length) {
    $("lista-estudios").innerHTML = "<tr><td>Todavía no hay estudios. Corre: python -m tradinglab barrido</td></tr>";
    return;
  }
  $("lista-estudios").innerHTML = tabla(
    ["#", "Fecha (UTC)", "Tipo", "Simulaciones", "Commit", "Descripción"],
    estudios.map(
      (e) => `<tr data-id="${e.id}"><td>#${e.id}</td><td>${fecha(e.creado_ms)}</td><td>${esc(e.tipo)}</td>` +
        `<td>${entero(e.combinaciones)}</td><td>${esc(e.commit_git || "-")}</td><td class="izq">${esc(e.descripcion)}</td></tr>`
    )
  );
  document.querySelectorAll("#lista-estudios tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => {
      document.querySelectorAll("#lista-estudios tr").forEach((x) => x.classList.remove("seleccionada"));
      tr.classList.add("seleccionada");
      verEstudio(Number(tr.dataset.id));
    })
  );
}

function tarjeta(valor, etiqueta) {
  return `<div class="tarjeta"><div class="valor">${valor}</div><div class="etiqueta">${esc(etiqueta)}</div></div>`;
}

function tablaCorridas(corridas, conMuestra) {
  const filas = corridas.map((c, i) => {
    const gana = c.rendimiento > 0 && c.rendimiento > c.bh_rendimiento;
    return `<tr data-i="${i}"><td>${esc(c.simbolo)} ${esc(c.intervalo)}</td><td class="izq">${esc(c.ventana)}</td>` +
      `<td class="izq">${esc(c.estrategia)} ${esc(textoParametros(c.parametros))}</td>` +
      `<td class="${clase(c.rendimiento)}">${pct(c.rendimiento)}</td><td class="${clase(c.bh_rendimiento)}">${pct(c.bh_rendimiento)}</td>` +
      `<td>${pct(c.drawdown_maximo)}</td><td>${entero(c.operaciones)}</td><td>${siNo(gana)}</td></tr>`;
  });
  return tabla(["Serie", "Ventana", "Estrategia", "Rendimiento", "Comprar y mantener", "Drawdown", "Ops", "¿Gana a las dos?"], filas);
}

function conectarFilas(idTabla, corridas) {
  document.querySelectorAll(`#${idTabla} tbody tr`).forEach((tr) =>
    tr.addEventListener("click", () => abrirEnBacktest(corridas[Number(tr.dataset.i)]))
  );
}

async function verEstudio(id) {
  const destino = $("detalle-estudio");
  destino.innerHTML = "<p class='descripcion'>Cargando...</p>";
  let e;
  try {
    e = await api(`/api/estudios/${id}`);
  } catch (error) {
    destino.innerHTML = `<p class="mensaje">${esc(error.message)}</p>`;
    return;
  }
  let html = `<h2>Estudio #${e.id}: ${esc(e.descripcion)} <small>${esc(e.tipo)} · commit ${esc(e.commit_git || "-")}</small></h2>`;

  if (e.tipo === "barrido") {
    const t = e.resumen.total;
    html += `<div class="tarjetas">${tarjeta(entero(t.corridas), "simulaciones (dentro de muestra)")}` +
      tarjeta(pct(t.ganan_a_no_operar / t.corridas, false), "le ganan a no operar") +
      tarjeta(pct(t.ganan_a_comprar_y_mantener / t.corridas, false), "le ganan a comprar y mantener") +
      tarjeta(pct(t.ganan_a_ambas / t.corridas, false), "le ganan a las dos") + "</div>";
    html += "<h2>Por ventana</h2><div class='desplazable'><table class='tabla'>" +
      tabla(["Serie", "Ventana", "Comprar y mantener", "Mediana", "Mejor", "Mejor combinación", "Ganan a las dos"],
        e.resumen.por_ventana.map((g) => `<tr><td>${esc(g.simbolo)} ${esc(g.intervalo)}</td><td class="izq">${esc(g.ventana)}</td>` +
          `<td class="${clase(g.bh_rendimiento)}">${pct(g.bh_rendimiento)}</td><td class="${clase(g.mediana)}">${pct(g.mediana)}</td>` +
          `<td class="${clase(g.mejor.rendimiento)}">${pct(g.mejor.rendimiento)}</td>` +
          `<td class="izq">${esc(g.mejor.estrategia)} ${esc(textoParametros(JSON.parse(g.mejor.parametros)))}</td>` +
          `<td>${g.ganan_a_ambas}/${g.corridas}</td></tr>`)) + "</table></div>";
    const mejores = [...e.corridas].sort((a, b) => b.rendimiento - a.rendimiento).slice(0, 200);
    html += "<h2>Las 200 corridas con mayor rendimiento <small>infladas por suerte: son las mejores de muchas. Clic para verlas</small></h2>" +
      `<div class="desplazable"><table id="corridas-estudio" class="tabla clicable">${tablaCorridas(mejores)}</table></div>`;
    destino.innerHTML = html;
    conectarFilas("corridas-estudio", mejores);
    return;
  }

  if (e.tipo === "walk_forward") {
    const rs = e.resumen.resumenes;
    const ganan = rs.filter((r) => r.le_gana_a_no_operar && r.le_gana_a_comprar_y_mantener).length;
    html += `<div class="tarjetas">${tarjeta(rs.length, "configuraciones evaluadas")}` +
      tarjeta(rs.filter((r) => r.le_gana_a_no_operar).length, "le ganan a no operar (fuera de muestra)") +
      tarjeta(rs.filter((r) => r.le_gana_a_comprar_y_mantener).length, "le ganan a comprar y mantener") +
      tarjeta(ganan, "le ganan a las dos") + tarjeta(entero(e.combinaciones), "simulaciones corridas") + "</div>";
    html += "<h2>Resultado fuera de muestra <small>pruebas encadenadas</small></h2><div class='desplazable'><table class='tabla'>" +
      tabla(["Serie", "Estrategia", "Rendimiento", "Drawdown", "Ops", "Comprar y mantener", "Mensual entren. → prueba", "¿Gana a no operar?", "¿Gana a C&M?"],
        rs.map((r) => `<tr><td>${esc(r.simbolo)} ${esc(r.intervalo)}</td><td class="izq">${esc(r.estrategia)}</td>` +
          `<td class="${clase(r.rendimiento)}">${pct(r.rendimiento)}</td><td>${pct(r.drawdown_maximo)}</td><td>${entero(r.operaciones)}</td>` +
          `<td class="${clase(r.bh_rendimiento)}">${pct(r.bh_rendimiento)}</td>` +
          `<td>${pct(r.mensual_entrenamiento_promedio)} → ${pct(r.mensual_prueba_promedio)}</td>` +
          `<td>${siNo(r.le_gana_a_no_operar)}</td><td>${siNo(r.le_gana_a_comprar_y_mantener)}</td></tr>`)) + "</table></div>";
    html += "<h2>Cada periodo de prueba <small>con la combinación elegida en su entrenamiento. Clic para verlo</small></h2>" +
      `<div class="desplazable"><table id="corridas-estudio" class="tabla clicable">${tablaCorridas(e.corridas)}</table></div>`;
    destino.innerHTML = html;
    conectarFilas("corridas-estudio", e.corridas);
    return;
  }

  if (e.tipo === "eventos") {
    html += "<p class='descripcion'>¿Algún factor avisa ANTES de las caídas fuertes? 'Se sostiene' = el quintil con más caídas " +
      "en entrenamiento también concentra caídas (al menos 1.25 veces la tasa base) en la prueba, que no se usó para nada. " +
      "Los factores (ref.) salen del propio precio. 'Vs. volatilidad' = caídas en el quintil riesgoso entre las que predeciría la " +
      "volatilidad sola: cerca de 1.00x, el factor solo repite la volatilidad. '¿Agrega?' = se sostiene y queda en 1.20x o más en los dos periodos.</p>";
    for (const r of e.resumen.resultados) {
      html += `<h2>${esc(r.simbolo)} ${esc(r.intervalo)} <small>caída = ${pct(r.umbral_caida)} o peor en ${r.horizonte_h} h · ` +
        `${r.entrenamiento.caidas_independientes} caídas independientes en entrenamiento, ${r.prueba.caidas_independientes} en prueba ` +
        `(desde ${dia(r.corte_ms)})</small></h2>`;
      html += "<div class='desplazable'><table class='tabla'>" + tabla(
        ["Factor", "Datos desde", "Corr. entren.", "Corr. prueba", "Quintil con más caídas", "P(caída) entren.", "P(caída) prueba",
          "¿Se sostiene?", "Vs. volatilidad (ent. → prueba)", "¿Agrega?"],
        r.factores.map((f) => {
          const nombre = esc(f.factor) + (f.referencia ? " (ref.)" : "");
          if (!f.evaluado) return `<tr><td>${nombre}</td><td class="izq">${f.desde_ms ? dia(f.desde_ms) : "sin datos"}</td><td colspan="8">pocos datos</td></tr>`;
          const x = (v) => (v === null ? "-" : v.toFixed(2) + "x");
          return `<tr><td>${nombre}</td><td class="izq">${dia(f.desde_ms)}</td>` +
            `<td>${f.correlacion_entrenamiento.toFixed(3)}</td><td>${f.correlacion_prueba.toFixed(3)}</td><td>${f.quintil_riesgoso}</td>` +
            `<td>${pct(f.p_caida_entrenamiento, false)} (${x(f.lift_entrenamiento)})</td>` +
            `<td class="${f.se_sostiene ? "positivo" : ""}">${pct(f.p_caida_prueba, false)} (${x(f.lift_prueba)})</td>` +
            `<td>${siNo(f.se_sostiene)}</td>` +
            (f.referencia ? "<td>-</td><td>-</td>"
              : `<td>${x(f.sobre_volatilidad_entrenamiento ?? null)} → ${x(f.sobre_volatilidad_prueba ?? null)}</td>` +
                `<td class="${f.agrega_sobre_volatilidad ? "positivo" : ""}">${siNo(f.agrega_sobre_volatilidad)}</td>`) +
            "</tr>";
        })) + "</table></div>";
    }
    destino.innerHTML = html;
    return;
  }

  html += `<div class="desplazable"><table id="corridas-estudio" class="tabla clicable">${tablaCorridas(e.corridas)}</table></div>`;
  destino.innerHTML = html;
  conectarFilas("corridas-estudio", e.corridas);
}

// ---------------------------------------------------------------------------------------
// Papel
// ---------------------------------------------------------------------------------------

async function cargarPapel() {
  let sesiones;
  try {
    sesiones = await api("/api/papel");
  } catch (error) {
    $("lista-papel").innerHTML = `<tr><td>${esc(error.message)}</td></tr>`;
    return;
  }
  if (!sesiones.length) {
    $("lista-papel").innerHTML =
      "<tr><td>No hay sesiones. Ejemplo: python -m tradinglab papel --simbolo BTCUSDT --intervalo 5m --estrategia cruce_medias</td></tr>";
    return;
  }
  $("lista-papel").innerHTML = tabla(
    ["Sesión", "Serie", "Estrategia", "Capital (USDT)", "Rendimiento", "Posición", "Último precio", "Actualizada (UTC)"],
    sesiones.map(
      (s) => `<tr data-nombre="${esc(s.nombre)}" class="${s.nombre === estado.papelActiva ? "seleccionada" : ""}">` +
        `<td>${esc(s.nombre)}</td><td>${esc(s.simbolo)} ${esc(s.intervalo)}</td><td class="izq">${esc(s.estrategia)} ${esc(textoParametros(s.parametros))}</td>` +
        `<td>${usd(s.capital)}</td><td class="${clase(s.rendimiento)}">${pct(s.rendimiento)}</td>` +
        `<td>${s.cantidad > 0 ? "comprado" : "fuera"}</td><td>${s.ultimo_precio ? s.ultimo_precio.toLocaleString("es-MX") : "-"}</td>` +
        `<td>${fecha(s.actualizada_ms)}</td></tr>`
    )
  );
  document.querySelectorAll("#lista-papel tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => {
      estado.papelActiva = tr.dataset.nombre;
      cargarPapel();
    })
  );
  if (estado.papelActiva) verSesionPapel(estado.papelActiva);
}

async function verSesionPapel(nombre) {
  let d;
  try {
    d = await api(`/api/papel/${encodeURIComponent(nombre)}`);
  } catch (error) {
    return;
  }
  $("detalle-papel").classList.remove("oculto");
  const s = d.sesion;
  const bh = s.bh_rendimiento === null || s.bh_rendimiento === undefined ? "" : ` · comprar y mantener desde el inicio: ${pct(s.bh_rendimiento)}`;
  $("titulo-papel").textContent = `${s.nombre}: ${s.simbolo} ${s.intervalo}, ${s.estrategia} ${textoParametros(s.parametros)}${bh}`;
  if (estado.papelDibujada !== nombre) {
    // Sesión nueva en pantalla: se crean las gráficas. Si es la misma, solo se actualizan los datos (no se pierde el zoom).
    estado.graficasPapel.forEach((g) => g.remove());
    const gVelas = crearGrafica("grafica-papel");
    const gCapital = crearGrafica("grafica-papel-capital");
    estado.seriesPapel = {
      velas: seriesVelas(gVelas),
      capital: gCapital.addLineSeries({ color: COLOR_ESTRATEGIA, lineWidth: 2, priceLineVisible: false }),
    };
    estado.graficasPapel = [gVelas, gCapital];
    estado.papelDibujada = nombre;
  }
  estado.seriesPapel.velas.setData(d.velas);
  estado.seriesPapel.velas.setMarkers(marcadores(d.marcas));
  estado.seriesPapel.capital.setData(d.capital);
  if (!estado.papelAjustada || estado.papelAjustada !== nombre) {
    estado.graficasPapel.forEach((g) => g.timeScale().fitContent());
    estado.papelAjustada = nombre;
  }
  $("operaciones-papel").innerHTML = tabla(
    ["Fecha (UTC)", "Lado", "Precio", "Cantidad", "Comisión", "Efectivo después"],
    d.operaciones.slice().reverse().map(
      (o) => `<tr><td>${fecha(o.ts)}</td><td>${esc(o.lado)}</td><td>${o.precio.toLocaleString("es-MX")}</td>` +
        `<td>${o.cantidad.toFixed(6)}</td><td>${usd(o.comision)}</td><td>${usd(o.efectivo)}</td></tr>`
    )
  );
}

setInterval(() => {
  if ($("vista-papel").classList.contains("activa")) cargarPapel();
}, 15000);

iniciar();
