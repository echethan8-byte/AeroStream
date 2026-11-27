(() => {
  const PHASE_COLORS = {
    APPROACH: "#38bdf8",
    DEPARTING: "#f59e0b",
    ENROUTE: "#818cf8",
    GROUND: "#10b981",
  };

  const state = {
    airport: "BLR",
    view: "all",
    direction: "ALL",
    status: "ALL",
    search: "",
    intervalMs: 5000,
    timerId: null,
    data: null,
    map: null,
    mapLayers: null,
    lastAirportCentered: null,
    charts: {},
  };

  const $ = (id) => document.getElementById(id);

  function fmtTime(iso) {
    if (!iso) return "--:--";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      // Postgres naive local timestamp like "2026-11-27T01:20:00"
      const m = String(iso).match(/T(\d{2}:\d{2})/);
      return m ? m[1] : String(iso);
    }
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function fmtTimeShort(iso) {
    if (!iso) return "--:--";
    const m = String(iso).match(/T(\d{2}:\d{2})/);
    return m ? m[1] : fmtTime(iso);
  }

  function fmtAgo(iso) {
    if (!iso) return "unknown";
    const ms = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(ms)) return iso;
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  }

  function riskPillClass(risk) {
    if (risk === "HIGH_RISK" || risk === "SEVERE" || risk === "HIGH") return "pill-rose";
    if (risk === "CAUTION" || risk === "MODERATE") return "pill-amber";
    if (risk === "NORMAL" || risk === "LOW" || risk === "OK") return "pill-green";
    return "pill-slate";
  }

  function statusPillClass(status) {
    switch (status) {
      case "Landed": return "pill-green";
      case "In air": return "pill-cyan";
      case "Delayed": return "pill-amber";
      case "Cancelled":
      case "Incident":
      case "Diverted": return "pill-rose";
      default: return "pill-indigo";
    }
  }

  function planeIcon(phase, heading) {
    const color = PHASE_COLORS[phase] || "#cbd5e1";
    const deg = Number.isFinite(heading) ? heading : 0;
    const svg = `
      <svg width="24" height="24" viewBox="0 0 24 24" style="transform: rotate(${deg}deg); filter: drop-shadow(0 0 4px rgba(0,0,0,0.9));">
        <path d="M12 2 L14.5 9 L21 12 L14.5 14 L14.5 19 L17 21 L12 20 L7 21 L9.5 19 L9.5 14 L3 12 L9.5 9 Z"
              fill="${color}" stroke="#070b14" stroke-width="1"/>
      </svg>`;
    return L.divIcon({
      html: svg,
      className: "plane-marker",
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
  }

  function initMap(lat, lon) {
    if (typeof L === "undefined") {
      $("radar-map").innerHTML = '<div class="empty-state">Map library unavailable offline — telemetry shown on the right.</div>';
      return;
    }
    if (!state.map) {
      state.map = L.map("radar-map", { zoomControl: true, attributionControl: false }).setView([lat, lon], 10);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
      }).addTo(state.map);
      state.mapLayers = L.layerGroup().addTo(state.map);
      state.lastAirportCentered = state.airport;
    } else if (state.lastAirportCentered !== state.airport) {
      state.map.setView([lat, lon], 10);
      state.lastAirportCentered = state.airport;
    }
  }

  function renderRadar(data) {
    const ap = data.selected_airport;
    const listEl = $("aircraft-list");
    const aircraft = data.aircraft || [];

    if (ap && typeof L !== "undefined") {
      initMap(ap.latitude, ap.longitude);
      state.mapLayers.clearLayers();

      // Terminal area radius (~111 km per degree)
      const terminalMeters = (data.terminal_radius_deg || 0.25) * 111000;
      L.circle([ap.latitude, ap.longitude], {
        radius: terminalMeters,
        color: "#38bdf8",
        weight: 1,
        dashArray: "5 5",
        fillColor: "#38bdf8",
        fillOpacity: 0.04,
      }).addTo(state.mapLayers);

      L.circleMarker([ap.latitude, ap.longitude], {
        radius: 6,
        color: "#f8fafc",
        weight: 2,
        fillColor: "#38bdf8",
        fillOpacity: 1,
      })
        .bindPopup(`<b>${ap.airport_code} (${ap.icao_code})</b><br/>${ap.airport_name}`)
        .addTo(state.mapLayers);

      aircraft.forEach((ac) => {
        if (ac.latitude == null || ac.longitude == null) return;
        const alt = ac.altitude != null ? `${Math.round(ac.altitude)} m` : "--";
        const spd = ac.velocity != null ? `${Math.round(ac.velocity * 3.6)} km/h` : "--";
        const marker = L.marker([ac.latitude, ac.longitude], {
          icon: planeIcon(ac.phase, ac.heading),
        });
        marker.bindPopup(
          `<div style="font-family:monospace;font-size:12px;">
            <b>${ac.callsign || ac.icao24}</b> (${ac.phase || "N/A"})<br/>
            ICAO24: ${ac.icao24}<br/>
            Alt: ${alt} &bull; Speed: ${spd}<br/>
            Heading: ${ac.heading != null ? Math.round(ac.heading) + "&deg;" : "--"}<br/>
            Weather risk: ${ac.weather_risk || "NORMAL"}
          </div>`
        );
        marker.addTo(state.mapLayers);
      });
    }

    if (!aircraft.length) {
      listEl.innerHTML = '<div class="empty-state">No aircraft tracked yet for this airport.</div>';
      return;
    }

    listEl.innerHTML = aircraft
      .map((ac) => {
        const alt = ac.altitude != null ? `${Math.round(ac.altitude)} m` : "GND";
        const spd = ac.velocity != null ? `${Math.round(ac.velocity * 3.6)} km/h` : "--";
        const hdg = ac.heading != null ? `${Math.round(ac.heading)}&deg;` : "--";
        const color = PHASE_COLORS[ac.phase] || "#cbd5e1";
        return `
          <div class="ac-item" data-lat="${ac.latitude}" data-lon="${ac.longitude}">
            <div class="ac-top">
              <span class="ac-callsign">${ac.callsign || ac.icao24}</span>
              <span class="pill" style="background:rgba(15,23,42,0.8);color:${color};border:1px solid ${color}55;">${ac.phase || "UNK"}</span>
            </div>
            <div class="ac-meta">
              <span>ALT ${alt}</span>
              <span>SPD ${spd}</span>
              <span>HDG ${hdg}</span>
            </div>
          </div>`;
      })
      .join("");

    listEl.querySelectorAll(".ac-item").forEach((el) => {
      el.addEventListener("click", () => {
        const lat = parseFloat(el.dataset.lat);
        const lon = parseFloat(el.dataset.lon);
        if (state.map && Number.isFinite(lat) && Number.isFinite(lon)) {
          state.map.flyTo([lat, lon], 12, { duration: 0.5 });
        }
      });
    });
  }

  function renderKPIs(data) {
    const k = data.passenger_kpis || {};
    const ac = data.aircraft_now || {};
    const ops = data.ops_current;

    $("kpi-arrivals").textContent = k.arrivals_today ?? 0;
    $("kpi-arrivals-sub").textContent = `Next hour: ${k.arrivals_next_hour ?? 0}`;

    $("kpi-departures").textContent = k.departures_today ?? 0;
    $("kpi-departures-sub").textContent = `Next hour: ${k.departures_next_hour ?? 0}`;

    const otp = k.on_time_percentage != null ? Number(k.on_time_percentage) : null;
    $("kpi-ontime").textContent = otp != null ? `${otp.toFixed(1)}%` : "--%";
    $("kpi-ontime-bar").style.width = `${otp != null ? Math.min(100, Math.max(0, otp)) : 0}%`;
    $("kpi-ontime-sub").textContent = `Delayed: ${k.delayed_flights ?? 0} • Cancelled: ${k.cancelled_flights ?? 0}`;

    $("kpi-delay").textContent = k.average_delay_min != null ? `${Number(k.average_delay_min).toFixed(1)} min` : "-- min";
    $("kpi-airspace").textContent = `${ac.airborne_aircraft ?? 0} / ${ac.ground_aircraft ?? 0}`;

    if (ops) {
      $("kpi-congestion").textContent = Number(ops.congestion_index).toFixed(2);
      $("kpi-congestion-sub").innerHTML = `<span class="pill ${riskPillClass(ops.congestion_level)}">${ops.congestion_level}</span> <span>${ops.total_movements} mov / 5m</span>`;
    } else {
      $("kpi-congestion").textContent = "--";
      $("kpi-congestion-sub").textContent = "Awaiting first 5m window";
    }
  }

  function renderWeather(data) {
    const w = data.weather;
    const pill = $("weather-risk-pill");
    if (!w) {
      pill.textContent = "NO DATA";
      pill.className = "pill pill-slate";
      $("weather-observed").textContent = "Observed: --";
      $("w-temp").innerHTML = "--&deg;C";
      $("w-wind-hero").textContent = "-- km/h";
      $("w-gusts").textContent = "Gusts: --";
      $("w-vis").textContent = "--";
      $("w-precip").textContent = "--";
      $("w-cloud").textContent = "--";
      $("w-dir").textContent = "--";
      return;
    }
    pill.textContent = w.weather_risk || "NORMAL";
    pill.className = `pill ${riskPillClass(w.weather_risk)}`;
    $("weather-observed").textContent = `Observed (local): ${fmtTimeShort(w.observed_local)}`;
    $("w-temp").innerHTML = w.temperature != null ? `${Number(w.temperature).toFixed(1)}&deg;C` : "--&deg;C";
    $("w-wind-hero").textContent = w.wind_speed != null ? `${Number(w.wind_speed).toFixed(1)} km/h` : "-- km/h";
    $("w-gusts").textContent = w.wind_gusts != null ? `Gusts: ${Number(w.wind_gusts).toFixed(1)} km/h` : "Gusts: --";
    $("w-vis").textContent = w.visibility != null ? `${(Number(w.visibility) / 1000).toFixed(1)} km` : "--";
    $("w-precip").textContent = w.precipitation != null ? `${Number(w.precipitation).toFixed(1)} mm` : "--";
    $("w-cloud").textContent = w.cloud_cover != null ? `${Math.round(w.cloud_cover)}%` : "--";
    $("w-dir").innerHTML = w.wind_direction != null ? `${Math.round(w.wind_direction)}&deg;` : "--";
  }

  function renderFIDS(data) {
    const all = data.passenger_flights || [];
    const q = state.search.trim().toLowerCase();
    const filtered = all.filter((f) => {
      if (state.direction !== "ALL" && f.direction !== state.direction) return false;
      if (state.status !== "ALL" && f.status !== state.status) return false;
      if (q) {
        const hay = `${f.flight_number || ""} ${f.airline || ""} ${f.city_airport || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    $("fids-count").textContent = `Showing ${filtered.length} of ${all.length} flights (-3h to +12h)`;
    const tbody = $("fids-tbody");
    if (!filtered.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No flights match the current filter.</td></tr>';
      return;
    }

    tbody.innerHTML = filtered
      .map((f) => {
        const dirBadge = f.direction === "ARRIVAL"
          ? '<span class="pill pill-cyan">ARR</span>'
          : '<span class="pill pill-indigo">DEP</span>';
        const delay = f.delay_minutes != null && f.delay_minutes > 0
          ? `<span class="mono" style="color:${f.delay_minutes > 15 ? "#fbbf24" : "#94a3b8"}">+${f.delay_minutes}m</span>`
          : '<span class="mono" style="color:#34d399">On time</span>';
        const gate = [f.terminal, f.gate ? `G${f.gate}` : null].filter(Boolean).join(" / ") || "--";
        return `
          <tr>
            <td><span class="flight-badge">${f.flight_number || "--"}</span></td>
            <td>${f.airline || "--"}</td>
            <td>${dirBadge}</td>
            <td class="mono">${f.city_airport || "--"}</td>
            <td class="mono">${fmtTimeShort(f.scheduled_local)}</td>
            <td class="mono">${fmtTimeShort(f.expected_local)}</td>
            <td>${delay}</td>
            <td class="mono">${gate}</td>
            <td><span class="pill ${statusPillClass(f.status)}">${f.status}</span></td>
          </tr>`;
      })
      .join("");
  }

  function upsertChart(key, canvasId, config) {
    if (typeof Chart === "undefined") return;
    if (state.charts[key]) {
      state.charts[key].data = config.data;
      state.charts[key].options = config.options;
      state.charts[key].update("none");
      return;
    }
    const ctx = $(canvasId).getContext("2d");
    state.charts[key] = new Chart(ctx, config);
  }

  function renderCharts(data) {
    if (typeof Chart === "undefined") return;
    Chart.defaults.color = "#94a3b8";
    Chart.defaults.borderColor = "rgba(148, 163, 184, 0.12)";
    Chart.defaults.font.family = "Inter, sans-serif";

    const m5 = data.metrics_5min || [];
    upsertChart("m5", "chart-5min", {
      type: "bar",
      data: {
        labels: m5.map((r) => fmtTime(r.window_start)),
        datasets: [
          {
            label: "Movements",
            data: m5.map((r) => r.total_movements),
            backgroundColor: "rgba(56, 189, 248, 0.45)",
            borderColor: "#38bdf8",
            borderWidth: 1,
            yAxisID: "y",
          },
          {
            type: "line",
            label: "Congestion Index",
            data: m5.map((r) => r.congestion_index),
            borderColor: "#f59e0b",
            backgroundColor: "#f59e0b",
            tension: 0.3,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Movements" } },
          y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Congestion" } },
        },
      },
    });

    const hr = data.hourly_ops || [];
    upsertChart("hourly", "chart-hourly", {
      type: "bar",
      data: {
        labels: hr.map((r) => fmtTimeShort(r.hour_local)),
        datasets: [
          { label: "Arrivals", data: hr.map((r) => r.arrivals), backgroundColor: "rgba(56, 189, 248, 0.55)" },
          { label: "Departures", data: hr.map((r) => r.departures), backgroundColor: "rgba(129, 140, 248, 0.55)" },
          {
            type: "line",
            label: "Avg Delay (m)",
            data: hr.map((r) => {
              const vals = [r.avg_arrival_delay_min, r.avg_departure_delay_min].filter((v) => v != null);
              return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
            }),
            borderColor: "#f43f5e",
            tension: 0.3,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true },
          y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } },
        },
      },
    });

    const counts = {};
    (data.passenger_flights || []).forEach((f) => {
      counts[f.status] = (counts[f.status] || 0) + 1;
    });
    const statusLabels = Object.keys(counts);
    const statusPalette = {
      Scheduled: "#818cf8",
      "In air": "#38bdf8",
      Delayed: "#f59e0b",
      Landed: "#10b981",
      Cancelled: "#f43f5e",
      Diverted: "#fb7185",
      Incident: "#e11d48",
    };
    upsertChart("status", "chart-status", {
      type: "doughnut",
      data: {
        labels: statusLabels,
        datasets: [{
          data: statusLabels.map((k) => counts[k]),
          backgroundColor: statusLabels.map((k) => statusPalette[k] || "#64748b"),
          borderColor: "#0f172a",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: { legend: { position: "bottom" } },
      },
    });

    const dw = data.delay_vs_weather || [];
    upsertChart("dw", "chart-delay-weather", {
      type: "bar",
      data: {
        labels: dw.map((r) => fmtTimeShort(r.hour_local)),
        datasets: [
          {
            label: "Avg Delay (min)",
            data: dw.map((r) => r.avg_delay_min),
            backgroundColor: "rgba(244, 63, 94, 0.55)",
            yAxisID: "y",
          },
          {
            type: "line",
            label: "Avg Wind (km/h)",
            data: dw.map((r) => r.avg_wind_kmh),
            borderColor: "#38bdf8",
            tension: 0.3,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Delay (min)" } },
          y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Wind (km/h)" } },
        },
      },
    });
  }

  function renderPipeline(data) {
    const items = data.pipeline_status || [];
    const el = $("pipeline-grid");
    if (!items.length) {
      el.innerHTML = '<div class="empty-state">No pipeline heartbeats recorded yet.</div>';
      return;
    }
    el.innerHTML = items
      .map((p) => `
        <div class="pipe-card">
          <div class="pipe-head">
            <span class="pipe-name">${p.component}</span>
            <span class="pill ${riskPillClass(p.status)}">${p.status}</span>
          </div>
          <div class="pipe-meta">
            <span>Published: <strong class="mono">${p.records_published ?? 0}</strong></span>
            <span>${fmtAgo(p.event_timestamp)}</span>
          </div>
          ${p.message ? `<div style="font-size:11px;color:#fda4af;">${p.message}</div>` : ""}
        </div>`)
      .join("");
  }

  function populateAirports(data) {
    const select = $("airport-select");
    const airports = data.airports || [];
    const monitored = data.monitored_airport || "BLR";
    if (!airports.length) return;
    select.innerHTML = airports
      .map((a) => {
        const tag = a.airport_code === monitored ? " • LIVE" : "";
        return `<option value="${a.airport_code}">${a.airport_code} — ${a.airport_name}${tag}</option>`;
      })
      .join("");
    select.value = data.airport_code;
    const ap = data.selected_airport;
    if (ap) {
      $("airport-subtitle").textContent = `${ap.airport_code} (${ap.icao_code}) • ${ap.airport_name}`;
    }

    const infoEl = $("info-banner");
    const hasData = Boolean((data.aircraft && data.aircraft.length) || (data.passenger_flights && data.passenger_flights.length) || data.weather);
    if (!hasData && data.airport_code !== monitored) {
      infoEl.innerHTML = `<span>No active stream for <strong>${data.airport_code}</strong>. The pipeline is currently configured to monitor <strong>${monitored}</strong> (set <code>AIRPORT_CODE=${data.airport_code}</code> in <code>.env</code> and restart to switch).</span><button id="jump-monitored-btn" class="btn" type="button">View ${monitored} Live</button>`;
      infoEl.style.display = "flex";
      $("jump-monitored-btn").addEventListener("click", () => {
        state.airport = monitored;
        refresh();
      });
    } else {
      infoEl.style.display = "none";
    }
  }

  function applyViewMode() {
    const v = state.view;
    $("section-radar").classList.toggle("hidden", v === "passenger");
    $("section-fids").classList.toggle("hidden", v === "ops");
    $("section-charts").classList.toggle("hidden", v === "passenger");
    $("section-ops-bottom").classList.toggle("hidden", v === "passenger");
    if (state.map && v !== "passenger") {
      setTimeout(() => state.map.invalidateSize(), 50);
    }
  }

  async function refresh() {
    const errEl = $("error-banner");
    const dotEl = $("live-dot");
    try {
      const res = await fetch(`/api/dashboard?airport=${encodeURIComponent(state.airport)}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.data = data;

      errEl.style.display = "none";
      dotEl.classList.remove("error");

      populateAirports(data);
      renderKPIs(data);
      renderWeather(data);
      renderRadar(data);
      renderFIDS(data);
      renderCharts(data);
      renderPipeline(data);
      $("last-sync").textContent = new Date().toLocaleTimeString([], { hour12: false });
    } catch (err) {
      dotEl.classList.add("error");
      errEl.textContent = `Unable to fetch live telemetry: ${err.message}`;
      errEl.style.display = "block";
    }
  }

  function resetTimer() {
    if (state.timerId) clearInterval(state.timerId);
    if (state.intervalMs > 0) {
      state.timerId = setInterval(refresh, state.intervalMs);
    }
  }

  function updateClock() {
    const tz = state.data?.selected_airport?.timezone || "Asia/Kolkata";
    try {
      $("local-clock").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: tz, hour12: false }) + ` (${tz.split("/")[1] || tz})`;
    } catch {
      $("local-clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
    }
  }

  document.querySelectorAll("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-view]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.view = btn.dataset.view;
      applyViewMode();
    });
  });

  document.querySelectorAll("[data-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-dir]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.direction = btn.dataset.dir;
      if (state.data) renderFIDS(state.data);
    });
  });

  $("airport-select").addEventListener("change", (e) => {
    state.airport = e.target.value;
    refresh();
  });

  $("refresh-select").addEventListener("change", (e) => {
    state.intervalMs = Number(e.target.value);
    resetTimer();
  });

  $("status-filter").addEventListener("change", (e) => {
    state.status = e.target.value;
    if (state.data) renderFIDS(state.data);
  });

  $("flight-search").addEventListener("input", (e) => {
    state.search = e.target.value;
    if (state.data) renderFIDS(state.data);
  });

  $("refresh-btn").addEventListener("click", refresh);

  setInterval(updateClock, 1000);
  updateClock();
  applyViewMode();
  refresh();
  resetTimer();
})();
