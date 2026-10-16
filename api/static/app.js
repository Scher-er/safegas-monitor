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

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    
    setTimeout(() => {
        toast.className = 'toast hidden';
    }, 3800);
}

// --- Modals Management ---
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('hidden');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('hidden');
}

// Fechar com ESC ou clique no overlay
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach(m => m.classList.add('hidden'));
    }
});

document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.add('hidden');
    });
});

// --- Tab Switching ---
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

// --- Alert Email Management ---
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
            showToast(`E-mail de alerta alterado para: ${result.dest_email}`, 'success');
            closeModal('modal-email');
        } else {
            showToast(result.error || 'Erro ao alterar e-mail', 'error');
        }
    } catch (err) {
        showToast('Falha na comunicação com o servidor', 'error');
    } finally {
        const btn = document.getElementById('btn-submit-email');
        btn.disabled = false;
        btn.textContent = 'Salvar Alterações';
    }
});

// --- Register Device Management ---
async function loadFormDropdowns() {
    try {
        // Carrega trabalhadores
        const resWorkers = await fetch(`${API_BASE}/workers`);
        const workers = await resWorkers.json();
        const selectWorkers = document.getElementById('reg-worker-id');
        selectWorkers.innerHTML = '<option value="">-- Nenhum (EPI em estoque) --</option>';
        for (const w of workers) {
            selectWorkers.innerHTML += `<option value="${w.worker_id}">${w.worker_id} - ${w.full_name} (${w.role})</option>`;
        }

        // Carrega locais
        const resLocs = await fetch(`${API_BASE}/locations`);
        const locations = await resLocs.json();
        const selectLocs = document.getElementById('reg-location-id');
        selectLocs.innerHTML = '<option value="">-- Nenhum / Não definido --</option>';
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
        btn.textContent = 'Cadastrando...';

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

            // Preenche e abre o modal de confirmação de início de funcionamento
            const titleEl = document.getElementById('confirm-start-title');
            const msgEl = document.getElementById('confirm-start-msg');
            if (titleEl) titleEl.textContent = `Equipamento ${pendingActivationDeviceId} Cadastrado!`;
            if (msgEl) {
                msgEl.innerHTML = `O equipamento <strong>${pendingActivationDeviceId}</strong> foi salvo com sucesso na base institucional.<br><br>Deseja adicionar o equipamento à tela principal e <strong>iniciar o funcionamento e simulação de dados em tempo real</strong> agora?`;
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
        btn.textContent = 'Salvar Equipamento';
    }
});

// Ações do Modal de Confirmação de Início de Operação
document.getElementById('btn-confirm-no').addEventListener('click', () => {
    const devId = pendingActivationDeviceId;
    closeModal('modal-confirm-start');
    showToast(`Equipamento ${devId || ''} cadastrado na base institucional.`, 'success');
    tabRegistryBtn.click();
    pendingActivationDeviceId = null;
});

document.getElementById('btn-confirm-yes').addEventListener('click', async () => {
    if (!pendingActivationDeviceId) return;
    const devId = pendingActivationDeviceId;
    const btnYes = document.getElementById('btn-confirm-yes');

    try {
        btnYes.disabled = true;
        btnYes.textContent = 'Iniciando...';

        const res = await fetch(`${API_BASE}/simulator/start-device`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: devId })
        });
        const result = await res.json();

        if (res.ok && result.success) {
            closeModal('modal-confirm-start');
            showToast(`Equipamento ${devId} em funcionamento e transmitindo via MQTT!`, 'success');
            // Alterna imediatamente para a tela principal (Em Monitoramento)
            tabLiveBtn.click();
            // Dispara atualização imediata dos dados
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

// --- Fetch Registered Devices (SQLite) ---
async function fetchRegisteredDevices() {
    try {
        const [devRes, simRes] = await Promise.all([
            fetch(`${API_BASE}/devices/registered`),
            fetch(`${API_BASE}/simulator/active`).catch(() => ({ json: () => [] }))
        ]);
        const devices = await devRes.json();
        const activeSims = simRes.ok ? await simRes.json() : [];
        const activeIds = new Set(activeSims.map(s => s.device_id));
        
        const tbody = document.getElementById('registry-body');
        if (!devices || devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Nenhum equipamento registrado no banco.</td></tr>';
            return;
        }

        let html = '';
        for (const d of devices) {
            const statusLower = (d.status || 'ACTIVE').toLowerCase();
            const isSimActive = activeIds.has(d.device_id);

            const actionBtn = isSimActive
                ? `<span style="display:inline-flex; align-items:center; gap:4px; font-size:11px; padding:3px 8px; border-radius:4px; background:#064e3b; color:#a7f3d0; border:1px solid #059669; font-weight:600;"><span style="color:#34d399">●</span> Ativo</span>`
                : `<button type="button" class="btn btn-secondary" style="padding:4px 10px; font-size:12px;" onclick="startSingleDevice('${d.device_id}')">▶ Iniciar</button>`;

            html += `
                <tr>
                    <td style="font-weight:600; color:var(--color-brand)">${d.device_id}</td>
                    <td>
                        <div>${d.model}</div>
                        <small class="text-muted">${d.manufacturer}</small>
                    </td>
                    <td><code>${d.serial_number}</code></td>
                    <td><span class="status-pill ${statusLower}">${d.status}</span></td>
                    <td>
                        <div>${d.calibration_date}</div>
                        <small class="text-muted">Próx: ${d.next_calibration}</small>
                    </td>
                    <td>${d.worker_name}</td>
                    <td>${d.location_name}</td>
                    <td>${actionBtn}</td>
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
            showToast(`Equipamento ${deviceId} ativado e transmitindo!`, 'success');
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

// --- Fetch Telemetry Data ---
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

// Initial loads
fetchAlertEmail();
setDefaultDates();
loadFormDropdowns();
updateAll();

// Update telemetry every 500ms
setInterval(updateAll, 500);
