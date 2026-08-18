// SafeGas Monitor - Web Dashboard Logic

const API_BASE = '/api';

// --- Utils ---
function formatUptime(seconds) {
    const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${h}:${m}:${s}`;
}

function getStatusClass(level) {
    return `status status-${level}`;
}

// --- Fetch Data ---
async function fetchStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const stats = await res.json();
        
        if (Object.keys(stats).length > 0) {
            document.getElementById('val-uptime').textContent = formatUptime(stats.uptime_s || 0);
            document.getElementById('val-devices').textContent = stats.devices_count || 0;
            document.getElementById('val-pps').textContent = (stats.throughput_pps || 0).toFixed(1);
            document.getElementById('val-incidents').textContent = stats.incidents_count || 0;
        }
    } catch (e) { console.error("Error fetching stats:", e); }
}

async function fetchDevices() {
    try {
        const res = await fetch(`${API_BASE}/devices`);
        const devices = await res.json();
        
        const tbody = document.getElementById('devices-body');
        if (devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Nenhum EPI conectado...</td></tr>';
            return;
        }
        
        let html = '';
        for (const d of devices) {
            const riskStr = d.risk_ratio >= 100.0 ? `<span class="risk-high">${d.risk_ratio.toFixed(1)}%</span>` : `${d.risk_ratio.toFixed(1)}%`;
            html += `
                <tr>
                    <td class="text-center text-muted">${d.last_seen}</td>
                    <td style="font-weight:600">${d.device_id}</td>
                    <td>${d.worker_id}</td>
                    <td class="text-right">${riskStr}</td>
                    <td class="text-center"><span class="${getStatusClass(d.alert_level)}">${d.alert_level}</span></td>
                    <td class="text-right">${d.temperature_c.toFixed(1)}</td>
                    <td class="text-right text-muted">${d.packets}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) { console.error("Error fetching devices:", e); }
}

async function fetchHistory() {
    try {
        const res = await fetch(`${API_BASE}/history`);
        const history = await res.json();
        
        const tbody = document.getElementById('history-body');
        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Nenhum evento detectado</td></tr>';
            return;
        }
        
        let html = '';
        for (const h of history) {
            html += `
                <tr>
                    <td class="text-center text-muted">${h.timestamp}</td>
                    <td style="font-weight:600">${h.device_id}</td>
                    <td class="text-center"><span class="${getStatusClass(h.alert_level)}">${h.alert_level}</span></td>
                    <td class="text-right"><span style="color:var(--color-${h.alert_level.toLowerCase()})">${h.risk_ratio.toFixed(1)}%</span></td>
                    <td>${h.gases}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) { console.error("Error fetching history:", e); }
}

async function fetchIncidents() {
    try {
        const res = await fetch(`${API_BASE}/incidents`);
        const incidents = await res.json();
        
        const tbody = document.getElementById('incidents-body');
        if (incidents.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Nenhum incidente crítico</td></tr>';
            return;
        }
        
        let html = '';
        for (const i of incidents) {
            html += `
                <tr>
                    <td class="text-center text-muted">${i.timestamp}</td>
                    <td>${i.incident_id}</td>
                    <td style="font-weight:600">${i.device_id}</td>
                    <td class="text-right risk-high">${i.peak_risk_ratio.toFixed(1)}%</td>
                    <td style="color:var(--color-brand)">${i.latex_path}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) { console.error("Error fetching incidents:", e); }
}

// --- Main Loop ---
async function updateAll() {
    await Promise.all([
        fetchStats(),
        fetchDevices(),
        fetchHistory(),
        fetchIncidents()
    ]);
}

// Update every 500ms for near real-time feeling
setInterval(updateAll, 500);
updateAll(); // Initial load
