let chartSituacoes = null;
let chartEvolucao = null;

Chart.defaults.color = '#6C7293';
Chart.defaults.borderColor = '#000000';

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return '';
    }
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function situacaoBadgeClass(situacao) {
    const map = {
        EXPIRADO: 'bg-danger',
        EXPIRA_HOJE: 'bg-danger',
        'CRÍTICO': 'bg-danger',
        URGENTE: 'bg-warning text-dark',
        'ATENÇÃO': 'bg-warning text-dark',
        OK: 'bg-success'
    };
    return map[situacao] || 'bg-secondary';
}

function formatDate(value) {
    if (!value) {
        return '-';
    }
    return value;
}

function refreshTimestamp() {
    const el = document.getElementById('last-update');
    if (!el) return;
    const now = new Date();
    el.textContent = `Atualizado em ${now.toLocaleDateString('pt-BR')} ${now.toLocaleTimeString('pt-BR')}`;
}

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Falha ao consultar ${url}: ${response.status}`);
    }
    return response.json();
}

async function fetchJsonWithBody(url, method, data) {
    const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.error || `Falha em ${url}`);
    }
    return payload;
}

function setStatus(targetId, message, isError = false) {
    const el = document.getElementById(targetId);
    if (!el) return;
    el.textContent = message;
    el.classList.remove('text-danger', 'text-success', 'text-warning', 'text-light');
    el.classList.add(isError ? 'text-danger' : 'text-success');
}

function updateScheduleVisibility() {
    const recurrence = document.getElementById('schedule-recurrence').value;
    const weekdayWrap = document.getElementById('schedule-weekday-wrap');
    const monthdayWrap = document.getElementById('schedule-monthday-wrap');
    weekdayWrap.classList.toggle('d-none', recurrence !== 'weekly');
    monthdayWrap.classList.toggle('d-none', recurrence !== 'monthly');
}

function fillEmailForm(email) {
    document.getElementById('email-smtp-server').value = email.smtp_server || '';
    document.getElementById('email-smtp-port').value = email.smtp_port || 587;
    document.getElementById('email-remetente').value = email.remetente || '';
    document.getElementById('email-senha').value = '';
    document.getElementById('email-destinatarios').value = (email.destinatarios || []).join(', ');
}

function fillScheduleForm(schedule) {
    document.getElementById('schedule-enabled').value = String(!!schedule.enabled);
    document.getElementById('schedule-recurrence').value = schedule.recurrence || 'daily';
    document.getElementById('schedule-time').value = schedule.time || '08:00';
    document.getElementById('schedule-weekday').value = String(schedule.day_of_week ?? 0);
    document.getElementById('schedule-monthday').value = String(schedule.day_of_month ?? 1);
    updateScheduleVisibility();
}

async function loadConfigs() {
    const [emailConfig, scheduleConfig] = await Promise.all([
        fetchJson('/api/config/email'),
        fetchJson('/api/config/schedule')
    ]);
    fillEmailForm(emailConfig);
    fillScheduleForm(scheduleConfig);
}

async function saveEmailConfig() {
    const payload = {
        smtp_server: document.getElementById('email-smtp-server').value.trim(),
        smtp_port: Number(document.getElementById('email-smtp-port').value),
        remetente: document.getElementById('email-remetente').value.trim(),
        senha: document.getElementById('email-senha').value,
        destinatarios: document.getElementById('email-destinatarios').value.trim()
    };
    await fetchJsonWithBody('/api/config/email', 'POST', payload);
    setStatus('email-config-status', 'Configuração de email salva com sucesso.');
}

async function saveScheduleConfig() {
    const payload = {
        enabled: document.getElementById('schedule-enabled').value === 'true',
        recurrence: document.getElementById('schedule-recurrence').value,
        time: document.getElementById('schedule-time').value,
        day_of_week: Number(document.getElementById('schedule-weekday').value),
        day_of_month: Number(document.getElementById('schedule-monthday').value)
    };
    await fetchJsonWithBody('/api/config/schedule', 'POST', payload);
    setStatus('schedule-config-status', 'Agendamento salvo com sucesso.');
}

async function sendReportNow() {
    await fetchJsonWithBody('/api/scheduler/run-now', 'POST', {});
    setStatus('email-config-status', 'Relatório enviado agora com sucesso.');
}

function renderMetrics(data, alertasCount) {
    document.getElementById('metric-total-consultas').textContent = data.total_consultas || 0;
    document.getElementById('metric-dominios-unicos').textContent = data.dominios_unicos || 0;
    document.getElementById('metric-alertas').textContent = alertasCount;
    document.getElementById('metric-ok').textContent = data.situacoes?.OK || 0;
}

function renderDominios(dominios) {
    const body = document.getElementById('dominios-table-body');
    if (!body) return;

    if (!dominios.length) {
        body.innerHTML = '<tr><td colspan="7" class="text-center">Nenhum domínio encontrado.</td></tr>';
        return;
    }

    body.innerHTML = dominios.map((item) => {
        const badgeClass = situacaoBadgeClass(item.situacao);
        return `
            <tr>
                <td>${escapeHtml(item.dominio)}</td>
                <td>${escapeHtml(item.handle || '-')}</td>
                <td>${escapeHtml(formatDate(item.data_expiracao))}</td>
                <td>${item.dias_para_expiracao ?? '-'}</td>
                <td><span class="badge ${badgeClass}">${escapeHtml(item.situacao)}</span></td>
                <td>${escapeHtml(item.created_at || '-')}</td>
                <td><button class="btn btn-sm btn-primary" data-dominio-id="${item.id}">Detalhes</button></td>
            </tr>
        `;
    }).join('');
}

function renderAlertas(alertas) {
    const list = document.getElementById('alertas-list');
    if (!list) return;

    if (!alertas.length) {
        list.innerHTML = '<div class="text-success fw-bold">Nenhum alerta ativo no momento.</div>';
        return;
    }

    list.innerHTML = alertas.map((item) => {
        const badgeClass = situacaoBadgeClass(item.situacao);
        return `
            <div class="list-group-item bg-dark text-light border-secondary d-flex justify-content-between align-items-center mb-2 rounded">
                <div>
                    <div class="fw-bold">${escapeHtml(item.dominio)}</div>
                    <small>Expiração: ${escapeHtml(formatDate(item.data_expiracao))} | Dias: ${item.dias_para_expiracao ?? '-'}</small>
                </div>
                <span class="badge ${badgeClass}">${escapeHtml(item.situacao)}</span>
            </div>
        `;
    }).join('');
}

function renderCharts(stats) {
    const ctxSituacoes = document.getElementById('chart-situacoes').getContext('2d');
    const ctxEvolucao = document.getElementById('chart-evolucao').getContext('2d');

    const labelsSituacao = stats.por_situacao.map((item) => item.situacao);
    const valuesSituacao = stats.por_situacao.map((item) => item.count);

    const labelsEvolucao = stats.evolucao.map((item) => item.data);
    const valuesEvolucao = stats.evolucao.map((item) => item.count);

    if (chartSituacoes) chartSituacoes.destroy();
    if (chartEvolucao) chartEvolucao.destroy();

    chartSituacoes = new Chart(ctxSituacoes, {
        type: 'doughnut',
        data: {
            labels: labelsSituacao,
            datasets: [{
                data: valuesSituacao,
                backgroundColor: [
                    'rgba(235, 22, 22, 0.8)',
                    'rgba(255, 193, 7, 0.8)',
                    'rgba(25, 135, 84, 0.8)',
                    'rgba(13, 110, 253, 0.8)',
                    'rgba(111, 66, 193, 0.8)',
                    'rgba(108, 117, 125, 0.8)'
                ]
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });

    chartEvolucao = new Chart(ctxEvolucao, {
        type: 'line',
        data: {
            labels: labelsEvolucao,
            datasets: [{
                label: 'Consultas',
                data: valuesEvolucao,
                borderColor: 'rgba(235, 22, 22, 0.9)',
                backgroundColor: 'rgba(235, 22, 22, 0.35)',
                fill: true,
                tension: 0.25
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
}

async function loadDominioDetails(dominioId) {
    const data = await fetchJson(`/api/dominio/${dominioId}`);
    const modalTitle = document.getElementById('dominioModalTitle');
    const modalBody = document.getElementById('dominioModalBody');

    const entidades = (data.entidades || []).map((entidade) => entidade.handle || entidade.nome || '-');
    const dnssec = (data.dnssec || []).map((item) => item.key_tag || item.algoritmo || item.delegacao_assinada || '-');

    modalTitle.textContent = `Detalhes: ${data.dominio?.dominio || ''}`;
    modalBody.innerHTML = `
        <div class="row g-3">
            <div class="col-md-6"><strong>Status:</strong> ${escapeHtml(data.dominio?.status || '-')}</div>
            <div class="col-md-6"><strong>Registro:</strong> ${escapeHtml(data.dominio?.data_registro || '-')}</div>
            <div class="col-md-6"><strong>Expiração:</strong> ${escapeHtml(data.dominio?.data_expiracao || '-')}</div>
            <div class="col-md-6"><strong>Dias para expiração:</strong> ${data.dominio?.dias_para_expiracao ?? '-'}</div>
        </div>
        <hr class="border-secondary">
        <h6 class="mb-2">Nameservers</h6>
        <ul>${(data.nameservers || []).map((ns) => `<li>${escapeHtml(ns.ldh_name || '-')}</li>`).join('') || '<li>-</li>'}</ul>
        <hr class="border-secondary">
        <h6 class="mb-2">Entidades</h6>
        <ul>${entidades.map((item) => `<li>${escapeHtml(item)}</li>`).join('') || '<li>-</li>'}</ul>
        <hr class="border-secondary">
        <h6 class="mb-2">DNSSEC</h6>
        <ul>${dnssec.map((item) => `<li>${escapeHtml(item)}</li>`).join('') || '<li>-</li>'}</ul>
    `;

    const modal = new bootstrap.Modal(document.getElementById('dominioModal'));
    modal.show();
}

function buildCsvUrl() {
    const search = document.getElementById('search-input').value.trim();
    const situacao = document.getElementById('situacao-filter').value;
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (situacao) params.set('situacao', situacao);
    const query = params.toString();
    return query ? `/api/exportar-csv?${query}` : '/api/exportar-csv';
}

async function loadAll() {
    const search = document.getElementById('search-input').value.trim();
    const situacao = document.getElementById('situacao-filter').value;
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (situacao) params.set('situacao', situacao);

    const query = params.toString();
    const dominiosUrl = query ? `/api/dominios?${query}` : '/api/dominios';

    const [dashboard, dominios, alertas, stats] = await Promise.all([
        fetchJson('/api/dashboard'),
        fetchJson(dominiosUrl),
        fetchJson('/api/alertas'),
        fetchJson('/api/stats')
    ]);

    renderMetrics(dashboard, alertas.length);
    renderDominios(dominios);
    renderAlertas(alertas);
    renderCharts(stats);
    refreshTimestamp();
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.rdap-nav-link').forEach((link) => {
        link.addEventListener('click', () => {
            document.querySelectorAll('.rdap-nav-link').forEach((item) => item.classList.remove('active'));
            link.classList.add('active');
        });
    });

    loadAll().catch((error) => {
        console.error(error);
    });

    loadConfigs().catch((error) => {
        setStatus('email-config-status', error.message, true);
    });

    document.getElementById('btn-refresh').addEventListener('click', (event) => {
        event.preventDefault();
        loadAll().catch((error) => console.error(error));
    });

    document.getElementById('situacao-filter').addEventListener('change', () => {
        loadAll().catch((error) => console.error(error));
    });

    document.getElementById('search-form').addEventListener('submit', (event) => {
        event.preventDefault();
        loadAll().catch((error) => console.error(error));
    });

    document.getElementById('btn-export').addEventListener('click', () => {
        window.location.href = buildCsvUrl();
    });

    document.getElementById('dominios-table-body').addEventListener('click', (event) => {
        const button = event.target.closest('button[data-dominio-id]');
        if (!button) return;
        const dominioId = button.getAttribute('data-dominio-id');
        loadDominioDetails(dominioId).catch((error) => console.error(error));
    });

    document.getElementById('schedule-recurrence').addEventListener('change', updateScheduleVisibility);

    document.getElementById('email-config-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await saveEmailConfig();
        } catch (error) {
            setStatus('email-config-status', error.message, true);
        }
    });

    document.getElementById('schedule-config-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await saveScheduleConfig();
        } catch (error) {
            setStatus('schedule-config-status', error.message, true);
        }
    });

    document.getElementById('btn-send-now').addEventListener('click', async () => {
        try {
            await sendReportNow();
        } catch (error) {
            setStatus('email-config-status', error.message, true);
        }
    });
});
