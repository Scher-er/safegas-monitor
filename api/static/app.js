// SafeGas Monitor - Script do Painel Web

const API_BASE = '/api';

// Relógio de Tempo Real e Alternador de Tema
function updateClock() {
    const el = document.getElementById('live-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleTimeString('pt-BR', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

const themeBtn = document.getElementById('btn-theme-toggle');
if (themeBtn) {
    const savedTheme = localStorage.getItem('safegas_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    themeBtn.textContent = savedTheme === 'dark' ? 'Tema: Escuro' : 'Tema: Claro';

    themeBtn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('safegas_theme', next);
        themeBtn.textContent = next === 'dark' ? 'Tema: Escuro' : 'Tema: Claro';
    });
}

// Funções Utilitárias
function formatUptime(seconds) {
    const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${h}:${m}:${s}`;
}

function getStatusClass(level) {
    return `status status-${level}`;
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast ${type}`;

    setTimeout(() => {
        toast.className = 'toast hidden';
    }, 3800);
}

// Controle de Modais
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('hidden');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('hidden');
}

window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.add('hidden'));
    }
});

document.querySelectorAll('.modal-backdrop').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.add('hidden');
    });
});

// Alternância de Abas (Telemetria vs Inventário SQLite)
let currentTab = 'live';

const tabLiveBtn = document.getElementById('tab-live-btn');
const tabRegistryBtn = document.getElementById('tab-registry-btn');
const containerLive = document.getElementById('container-live-devices');
const containerRegistry = document.getElementById('container-registry-devices');

tabLiveBtn.addEventListener('click', () => {
    currentTab = 'live';
    tabLiveBtn.classList.add('active');
    tabRegistryBtn.classList.remove('active');
    containerLive.classList.remove('hidden');
    containerRegistry.classList.add('hidden');
});

tabRegistryBtn.addEventListener('click', () => {
    currentTab = 'registry';
    tabRegistryBtn.classList.add('active');
    tabLiveBtn.classList.remove('active');
    containerRegistry.classList.remove('hidden');
    containerLive.classList.add('hidden');
    fetchRegisteredDevices();
});

// Configuração de E-mail de Alerta
async function fetchAlertEmail() {
    try {
        const res = await fetch(`${API_BASE}/settings/email`);
        const data = await res.json();
        if (data.dest_email) {
            document.getElementById('header-dest-email').textContent = data.dest_email;
            document.getElementById('input-email-dest').value = data.dest_email;
        }
    } catch (e) {
        console.error("Erro ao buscar e-mail de alerta:", e);
    }
}

document.getElementById('btn-email-modal').addEventListener('click', () => {
    openModal('modal-email');
});
document.getElementById('btn-close-email').addEventListener('click', () => closeModal('modal-email'));
document.getElementById('btn-cancel-email').addEventListener('click', () => closeModal('modal-email'));

document.getElementById('form-email-settings').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('input-email-dest').value.trim();
    if (!email) return;

    try {
        const btn = document.getElementById('btn-submit-email');
        btn.disabled = true;
        btn.textContent = 'Salvando...';

        const res = await fetch(`${API_BASE}/settings/email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dest_email: email })
        });
        const result = await res.json();

        if (res.ok && result.success) {
            document.getElementById('header-dest-email').textContent = result.dest_email;
            showToast(`Destinatário atualizado para: ${result.dest_email}`, 'success');
            closeModal('modal-email');
        } else {
            showToast(result.error || 'Erro ao alterar e-mail', 'error');
        }
    } catch (err) {
        showToast('Falha na comunicação com o servidor', 'error');
    } finally {
        const btn = document.getElementById('btn-submit-email');
        btn.disabled = false;
        btn.textContent = 'Atualizar Destinatário';
    }
});

// Cadastro de Novos Equipamentos
async function loadFormDropdowns() {
    try {
        const resWorkers = await fetch(`${API_BASE}/workers`);
        const workers = await resWorkers.json();
        const selectWorkers = document.getElementById('reg-worker-id');
        selectWorkers.innerHTML = '<option value="">-- Não alocado (Em estoque) --</option>';
        for (const w of workers) {
            selectWorkers.innerHTML += `<option value="${w.worker_id}">${w.worker_id} - ${w.full_name} (${w.role})</option>`;
        }

        const resLocs = await fetch(`${API_BASE}/locations`);
        const locations = await resLocs.json();
        const selectLocs = document.getElementById('reg-location-id');
        selectLocs.innerHTML = '<option value="">-- Não definido --</option>';
        for (const l of locations) {
            selectLocs.innerHTML += `<option value="${l.location_id}">${l.location_id} - ${l.name} [Risco: ${l.risk_level}]</option>`;
        }
    } catch (e) {
        console.error("Erro ao carregar opções para o cadastro:", e);
    }
}

function setDefaultDates() {
    const today = new Date();
    const todayStr = today.toISOString().split('T')[0];

    const nextCal = new Date();
    nextCal.setDate(nextCal.getDate() + 180);
    const nextCalStr = nextCal.toISOString().split('T')[0];

    document.getElementById('reg-calibration-date').value = todayStr;
    document.getElementById('reg-next-calibration').value = nextCalStr;
}

document.getElementById('btn-register-modal').addEventListener('click', () => {
    loadFormDropdowns();
    setDefaultDates();
    openModal('modal-register');
});
document.getElementById('btn-close-register').addEventListener('click', () => closeModal('modal-register'));
document.getElementById('btn-cancel-register').addEventListener('click', () => closeModal('modal-register'));

let pendingActivationDeviceId = null;

document.getElementById('form-register-device').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());

    try {
        const btn = document.getElementById('btn-submit-register');
        btn.disabled = true;
        btn.textContent = 'Registrando...';

        const res = await fetch(`${API_BASE}/devices/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await res.json();

        if (res.ok && result.success) {
            closeModal('modal-register');
            form.reset();
            setDefaultDates();
            fetchRegisteredDevices();

            pendingActivationDeviceId = result.device_id || payload.device_id;

            const titleEl = document.getElementById('confirm-start-title');
            const msgEl = document.getElementById('confirm-start-msg');
            if (titleEl) titleEl.textContent = `Equipamento ${pendingActivationDeviceId} Registrado`;
            if (msgEl) {
                msgEl.innerHTML = `O detector <strong>${pendingActivationDeviceId}</strong> foi gravado no banco relacional.<br><br>Deseja incluí-lo no painel principal e <strong>iniciar a transmissão de telemetria em tempo real</strong> agora?`;
            }
            openModal('modal-confirm-start');
        } else {
            showToast(result.error || 'Erro ao registrar equipamento', 'error');
        }
    } catch (err) {
        showToast('Falha na comunicação com o servidor', 'error');
    } finally {
        const btn = document.getElementById('btn-submit-register');
        btn.disabled = false;
        btn.textContent = 'Confirmar Registro';
    }
});

document.getElementById('btn-confirm-no').addEventListener('click', () => {
    const devId = pendingActivationDeviceId;
    closeModal('modal-confirm-start');
    showToast(`Equipamento ${devId || ''} registrado no inventário SQLite.`, 'success');
    tabRegistryBtn.click();
    pendingActivationDeviceId = null;
});

document.getElementById('btn-confirm-yes').addEventListener('click', async () => {
    if (!pendingActivationDeviceId) return;
    const devId = pendingActivationDeviceId;
    const btnYes = document.getElementById('btn-confirm-yes');

    try {
        btnYes.disabled = true;
        btnYes.textContent = 'Acionando...';

        const res = await fetch(`${API_BASE}/simulator/start-device`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: devId })
        });
        const result = await res.json();

        if (res.ok && result.success) {
            closeModal('modal-confirm-start');
            showToast(`Equipamento ${devId} ativo e transmitindo via MQTT.`, 'success');
            tabLiveBtn.click();
            fetchDevices();
            fetchStats();
        } else {
            showToast(result.error || 'Erro ao iniciar transmissão do equipamento', 'error');
        }
    } catch (err) {
        showToast('Falha de comunicação ao iniciar o equipamento', 'error');
    } finally {
        btnYes.disabled = false;
        btnYes.textContent = 'Sim, Iniciar Funcionamento';
        pendingActivationDeviceId = null;
    }
});

// Listagem do Inventário Relacional (SQLite)
async function fetchRegisteredDevices() {
    try {
        const [devRes, simRes] = await Promise.all([
            fetch(`${API_BASE}/devices/registered`),
            fetch(`${API_BASE}/simulator/active`).catch(() => ({ ok: false, json: () => [] }))
        ]);
        const devices = await devRes.json();
        const activeSims = simRes.ok ? await simRes.json() : [];
        const activeIds = new Set(activeSims.map(s => s.device_id));

        const tbody = document.getElementById('registry-body');
        if (!devices || devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-row">Nenhum equipamento registrado no banco SQLite.</td></tr>';
            return;
        }

        let html = '';
        for (const d of devices) {
            const statusLower = (d.status || 'ACTIVE').toLowerCase();
            const isSimActive = activeIds.has(d.device_id);

            const actionBtn = isSimActive
                ? `<span class="status status-NORMAL">TRANSMITINDO</span>`
                : `<button type="button" class="btn btn-secondary" style="padding:3px 10px; font-size:11.5px;" onclick="startSingleDevice('${d.device_id}')">Acionar EPI</button>`;

            html += `
                <tr>
                    <td class="mono" style="font-weight:600;">${d.device_id}</td>
                    <td>
                        <div style="font-weight:600;">${d.model}</div>
                        <small class="text-muted">${d.manufacturer}</small>
                    </td>
                    <td class="mono">${d.serial_number}</td>
                    <td><span class="status-pill ${statusLower}">${d.status}</span></td>
                    <td class="mono">
                        <div>${d.calibration_date}</div>
                        <small class="text-muted">Venc: ${d.next_calibration}</small>
                    </td>
                    <td>${d.worker_name}</td>
                    <td>${d.location_name}</td>
                    <td class="text-center">${actionBtn}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error("Erro ao listar equipamentos cadastrados:", e);
    }
}

window.startSingleDevice = async function(deviceId) {
    try {
        const res = await fetch(`${API_BASE}/simulator/start-device`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId })
        });
        const result = await res.json();
        if (res.ok && result.success) {
            showToast(`Equipamento ${deviceId} acionado na rede MQTT.`, 'success');
            tabLiveBtn.click();
            fetchDevices();
            fetchStats();
        } else {
            showToast(result.error || 'Erro ao iniciar transmissão', 'error');
        }
    } catch (e) {
        showToast('Falha na comunicação com o servidor', 'error');
    }
};

// Atualização de Telemetria em Tempo Real
async function fetchStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const stats = await res.json();

        if (Object.keys(stats).length > 0) {
            document.getElementById('val-uptime').textContent = formatUptime(stats.uptime_s || 0);
            document.getElementById('val-devices').textContent = stats.devices_count || 0;
            document.getElementById('val-pps').textContent = (stats.throughput_pps || 0).toFixed(1);
            document.getElementById('val-incidents').textContent = stats.incidents_count || 0;

            const mongoEl = document.getElementById('mongo-status');
            if (mongoEl) {
                if (stats.mongo_connected) {
                    mongoEl.textContent = `CONECTADO (${stats.mongo_db || 'safegas_monitor'})`;
                    mongoEl.style.color = '#4ade80';
                } else {
                    mongoEl.textContent = 'MODO OFFLINE';
                    mongoEl.style.color = '#fbbf24';
                }
            }
        }
    } catch (e) {
        console.error("Erro ao buscar estatisticas:", e);
    }
}

async function fetchDevices() {
    try {
        const res = await fetch(`${API_BASE}/devices`);
        const devices = await res.json();

        const tbody = document.getElementById('devices-body');
        if (devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-row">Nenhum detector conectado ao broker MQTT...</td></tr>';
            return;
        }

        let html = '';
        for (const d of devices) {
            const pctClamp = Math.min(100, Math.max(0, d.risk_ratio));
            const numClass = d.risk_ratio >= 50.0 ? 'risk-num risk-high' : 'risk-num';

            html += `
                <tr>
                    <td class="mono text-muted">${d.last_seen}</td>
                    <td class="mono" style="font-weight:600;">${d.device_id}</td>
                    <td>
                        <div style="font-weight:600;">${d.worker_id}</div>
                        <small class="text-muted">${d.location_id || ''}</small>
                    </td>
                    <td>
                        <div class="risk-cell">
                            <div class="risk-meter">
                                <div class="risk-fill fill-${d.alert_level}" style="width:${pctClamp.toFixed(1)}%"></div>
                            </div>
                            <span class="${numClass}">${d.risk_ratio.toFixed(1)}%</span>
                        </div>
                    </td>
                    <td class="text-center"><span class="${getStatusClass(d.alert_level)}">${d.alert_level}</span></td>
                    <td class="text-right mono">${d.temperature_c.toFixed(1)}</td>
                    <td class="text-right mono text-muted">${d.packets}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error("Erro ao buscar dispositivos:", e);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch(`${API_BASE}/history`);
        const history = await res.json();

        const tbody = document.getElementById('history-body');
        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Nenhuma anomalia registrada no turno atual.</td></tr>';
            return;
        }

        let html = '';
        for (const h of history) {
            html += `
                <tr>
                    <td class="mono text-muted">${h.timestamp}</td>
                    <td class="mono" style="font-weight:600;">${h.device_id}</td>
                    <td class="text-center"><span class="${getStatusClass(h.alert_level)}">${h.alert_level}</span></td>
                    <td class="text-right mono" style="font-weight:600;">${h.risk_ratio.toFixed(1)}%</td>
                    <td class="mono" style="font-size:11.5px;">${h.gases}</td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error("Erro ao buscar historico:", e);
    }
}

async function fetchIncidents() {
    try {
        const res = await fetch(`${API_BASE}/incidents`);
        const incidents = await res.json();

        const tbody = document.getElementById('incidents-body');
        if (incidents.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Nenhum incidente crítico registrado.</td></tr>';
            return;
        }

        let html = '';
        for (const i of incidents) {
            const reportUrl = `${API_BASE}/reports/${encodeURIComponent(i.latex_path)}`;
            html += `
                <tr>
                    <td class="mono text-muted">${i.timestamp}</td>
                    <td class="mono">#${i.incident_id}</td>
                    <td class="mono" style="font-weight:600;">${i.device_id}</td>
                    <td class="text-right risk-high">${i.peak_risk_ratio.toFixed(1)}%</td>
                    <td>
                        <a href="${reportUrl}" target="_blank" rel="noopener noreferrer" class="report-link" title="Clique para abrir o laudo técnico em nova aba">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                            <span>${i.latex_path}</span>
                        </a>
                    </td>
                </tr>
            `;
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error("Erro ao buscar incidentes:", e);
    }
}

async function updateAll() {
    await Promise.all([
        fetchStats(),
        fetchDevices(),
        fetchHistory(),
        fetchIncidents()
    ]);
}

fetchAlertEmail();
setDefaultDates();
loadFormDropdowns();
updateAll();

setInterval(updateAll, 500);
