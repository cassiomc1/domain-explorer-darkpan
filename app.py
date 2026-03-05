#!/usr/bin/env python3
"""
Interface Web para consulta de domínios RDAP
Servidor Flask com interface moderna em dark mode
"""

from flask import Flask, render_template, jsonify, request, Response
import sqlite3
from datetime import datetime
import json
import csv
import os
import threading
from io import StringIO
from consulta_whois_db import EMAIL_CONFIG, gerar_relatorio_email, enviar_email_relatorio

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

SETTINGS_FILE = 'web_settings.json'
settings_lock = threading.Lock()
scheduler_lock = threading.Lock()
scheduler_stop_event = threading.Event()
scheduler_thread = None

DEFAULT_WEB_SETTINGS = {
    'email': {
        'smtp_server': EMAIL_CONFIG.get('smtp_server', ''),
        'smtp_port': int(EMAIL_CONFIG.get('smtp_port', 587)),
        'remetente': EMAIL_CONFIG.get('remetente', ''),
        'senha': EMAIL_CONFIG.get('senha', ''),
        'destinatarios': EMAIL_CONFIG.get('destinatarios', [])
    },
    'schedule': {
        'enabled': False,
        'recurrence': 'daily',
        'time': '08:00',
        'day_of_week': 0,
        'day_of_month': 1,
        'last_run': ''
    }
}


def _deep_copy_defaults():
    return json.loads(json.dumps(DEFAULT_WEB_SETTINGS))


def load_web_settings():
    if not os.path.exists(SETTINGS_FILE):
        return _deep_copy_defaults()

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return _deep_copy_defaults()

    merged = _deep_copy_defaults()
    merged['email'].update(data.get('email', {}))
    merged['schedule'].update(data.get('schedule', {}))
    return merged


def save_web_settings(settings):
    with settings_lock:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)


def get_web_settings():
    with settings_lock:
        return load_web_settings()


def _parse_recipients(value):
    if isinstance(value, list):
        return [x.strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(',') if x.strip()]


def apply_email_settings(email_settings):
    EMAIL_CONFIG['smtp_server'] = email_settings.get('smtp_server', EMAIL_CONFIG.get('smtp_server', ''))
    EMAIL_CONFIG['smtp_port'] = int(email_settings.get('smtp_port', EMAIL_CONFIG.get('smtp_port', 587)))
    EMAIL_CONFIG['remetente'] = email_settings.get('remetente', EMAIL_CONFIG.get('remetente', ''))
    EMAIL_CONFIG['senha'] = email_settings.get('senha', EMAIL_CONFIG.get('senha', ''))
    EMAIL_CONFIG['destinatarios'] = _parse_recipients(email_settings.get('destinatarios', EMAIL_CONFIG.get('destinatarios', [])))


def _validate_time_str(value):
    try:
        hh, mm = value.split(':')
        hour = int(hh)
        minute = int(mm)
    except Exception:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _should_run_schedule(now, schedule):
    if not schedule.get('enabled'):
        return False

    if not _validate_time_str(schedule.get('time', '')):
        return False

    hour, minute = [int(x) for x in schedule.get('time', '08:00').split(':')]
    if now.hour != hour or now.minute != minute:
        return False

    recurrence = schedule.get('recurrence', 'daily')
    if recurrence == 'weekly' and now.weekday() != int(schedule.get('day_of_week', 0)):
        return False
    if recurrence == 'monthly' and now.day != int(schedule.get('day_of_month', 1)):
        return False

    last_run = schedule.get('last_run', '')
    if last_run:
        try:
            last_run_dt = datetime.fromisoformat(last_run)
            if last_run_dt.strftime('%Y-%m-%d %H:%M') == now.strftime('%Y-%m-%d %H:%M'):
                return False
        except ValueError:
            pass
    return True


def run_report_once():
    settings = get_web_settings()
    apply_email_settings(settings['email'])

    conn = get_db_connection()
    try:
        html_content, tem_alertas = gerar_relatorio_email(conn)
    finally:
        conn.close()

    return enviar_email_relatorio(html_content, tem_alertas, modo_teste=False)


def scheduler_loop():
    while not scheduler_stop_event.is_set():
        try:
            settings = get_web_settings()
            schedule = settings.get('schedule', {})
            now = datetime.now()

            if _should_run_schedule(now, schedule):
                with scheduler_lock:
                    success = run_report_once()
                    if success:
                        settings = get_web_settings()
                        settings['schedule']['last_run'] = now.isoformat()
                        save_web_settings(settings)
        except Exception as exc:
            print(f'Erro no scheduler: {exc}')

        scheduler_stop_event.wait(30)


def start_scheduler():
    global scheduler_thread
    if scheduler_thread and scheduler_thread.is_alive():
        return
    scheduler_stop_event.clear()
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

def get_db_connection():
    """Cria conexão com o banco de dados"""
    conn = sqlite3.connect('dominios_rdap.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/api/dashboard')
def dashboard():
    """Retorna dados do dashboard"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Estatísticas gerais
    cursor.execute('SELECT COUNT(*) as total FROM dominios')
    total_consultas = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(DISTINCT dominio) as total FROM dominios')
    dominios_unicos = cursor.fetchone()['total']
    
    # Distribuição por situação
    cursor.execute('''
        SELECT situacao, COUNT(*) as count
        FROM (
            SELECT dominio, situacao 
            FROM dominios 
            WHERE (dominio, created_at) IN (
                SELECT dominio, MAX(created_at) 
                FROM dominios 
                GROUP BY dominio
            )
        )
        GROUP BY situacao
    ''')
    
    situacoes = {}
    for row in cursor.fetchall():
        situacoes[row['situacao']] = row['count']
    
    # Últimas consultas
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, situacao, created_at
        FROM dominios
        ORDER BY created_at DESC
        LIMIT 10
    ''')
    
    ultimas_consultas = []
    for row in cursor.fetchall():
        ultimas_consultas.append({
            'dominio': row['dominio'],
            'data_expiracao': row['data_expiracao'],
            'dias_para_expiracao': row['dias_para_expiracao'],
            'situacao': row['situacao'],
            'created_at': row['created_at']
        })
    
    conn.close()
    
    return jsonify({
        'total_consultas': total_consultas,
        'dominios_unicos': dominios_unicos,
        'situacoes': situacoes,
        'ultimas_consultas': ultimas_consultas
    })

@app.route('/api/dominios')
def listar_dominios():
    """Lista todos os domínios (últimas consultas)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Parâmetros de busca e filtro
    search = request.args.get('search', '')
    situacao = request.args.get('situacao', '')
    
    query = '''
        SELECT d.id, d.dominio, d.handle, d.status, d.data_registro, 
               d.data_expiracao, d.dias_para_expiracao, d.situacao, d.created_at
        FROM dominios d
        WHERE (d.dominio, d.created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
    '''
    
    params = []
    
    if search:
        query += ' AND d.dominio LIKE ?'
        params.append(f'%{search}%')
    
    if situacao:
        query += ' AND d.situacao = ?'
        params.append(situacao)
    
    query += ''' ORDER BY 
        CASE d.situacao
            WHEN 'EXPIRADO' THEN 1
            WHEN 'EXPIRA_HOJE' THEN 2
            WHEN 'CRÍTICO' THEN 3
            WHEN 'URGENTE' THEN 4
            WHEN 'ATENÇÃO' THEN 5
            WHEN 'OK' THEN 6
            ELSE 7
        END,
        d.dias_para_expiracao
    '''
    
    cursor.execute(query, params)
    
    dominios = []
    for row in cursor.fetchall():
        dominios.append({
            'id': row['id'],
            'dominio': row['dominio'],
            'handle': row['handle'],
            'status': row['status'],
            'data_registro': row['data_registro'],
            'data_expiracao': row['data_expiracao'],
            'dias_para_expiracao': row['dias_para_expiracao'],
            'situacao': row['situacao'],
            'created_at': row['created_at']
        })
    
    conn.close()
    
    return jsonify(dominios)

@app.route('/api/exportar-csv')
def exportar_csv():
    """Exporta domínios filtrados em CSV"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Parâmetros de busca e filtro (mesmos da listagem)
    search = request.args.get('search', '')
    situacao = request.args.get('situacao', '')
    
    query = '''
        SELECT d.dominio, d.handle, d.status, d.data_registro, 
               d.data_expiracao, d.dias_para_expiracao, d.situacao, d.created_at
        FROM dominios d
        WHERE (d.dominio, d.created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
    '''
    
    params = []
    
    if search:
        query += ' AND d.dominio LIKE ?'
        params.append(f'%{search}%')
    
    if situacao:
        query += ' AND d.situacao = ?'
        params.append(situacao)
    
    query += ''' ORDER BY 
        CASE d.situacao
            WHEN 'EXPIRADO' THEN 1
            WHEN 'EXPIRA_HOJE' THEN 2
            WHEN 'CRÍTICO' THEN 3
            WHEN 'URGENTE' THEN 4
            WHEN 'ATENÇÃO' THEN 5
            WHEN 'OK' THEN 6
            ELSE 7
        END,
        d.dias_para_expiracao
    '''
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # Cria CSV em memória
    output = StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    
    # Cabeçalho
    writer.writerow([
        'Domínio',
        'Handle',
        'Status',
        'Data de Registro',
        'Data de Expiração',
        'Dias para Expiração',
        'Situação',
        'Última Consulta'
    ])
    
    # Dados
    for row in rows:
        writer.writerow([
            row['dominio'],
            row['handle'] or '',
            row['status'] or '',
            row['data_registro'] or '',
            row['data_expiracao'] or '',
            row['dias_para_expiracao'] if row['dias_para_expiracao'] is not None else '',
            row['situacao'],
            row['created_at']
        ])
    
    conn.close()
    
    # Prepara resposta
    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'dominios_rdap_{timestamp}.csv'
    
    csv_content = '\ufeff' + output.getvalue()

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@app.route('/api/dominio/<int:dominio_id>')
def detalhes_dominio(dominio_id):
    """Retorna detalhes completos de um domínio"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Dados principais
    cursor.execute('SELECT * FROM dominios WHERE id = ?', (dominio_id,))
    dominio = cursor.fetchone()
    
    if not dominio:
        conn.close()
        return jsonify({'error': 'Domínio não encontrado'}), 404
    
    # Nameservers
    cursor.execute('SELECT * FROM nameservers WHERE dominio_id = ?', (dominio_id,))
    nameservers = [dict(row) for row in cursor.fetchall()]
    
    # Entidades
    cursor.execute('SELECT * FROM entidades WHERE dominio_id = ?', (dominio_id,))
    entidades = [dict(row) for row in cursor.fetchall()]
    
    # DNSSEC
    cursor.execute('SELECT * FROM dnssec WHERE dominio_id = ?', (dominio_id,))
    dnssec = [dict(row) for row in cursor.fetchall()]
    
    # JSON completo
    cursor.execute('SELECT json_data FROM dados_completos WHERE dominio_id = ?', (dominio_id,))
    json_row = cursor.fetchone()
    json_completo = json.loads(json_row['json_data']) if json_row else None
    
    conn.close()
    
    return jsonify({
        'dominio': dict(dominio),
        'nameservers': nameservers,
        'entidades': entidades,
        'dnssec': dnssec,
        'json_completo': json_completo
    })

@app.route('/api/historico/<dominio>')
def historico_dominio(dominio):
    """Retorna histórico de consultas de um domínio"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Histórico de consultas
    cursor.execute('''
        SELECT id, dominio, status, data_expiracao, dias_para_expiracao, 
               situacao, created_at
        FROM dominios
        WHERE dominio = ?
        ORDER BY created_at DESC
    ''', (dominio,))
    
    historico = [dict(row) for row in cursor.fetchall()]
    
    # Histórico de mudanças de status
    cursor.execute('''
        SELECT * FROM historico_status
        WHERE dominio = ?
        ORDER BY data_mudanca DESC
    ''', (dominio,))
    
    mudancas = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return jsonify({
        'historico': historico,
        'mudancas': mudancas
    })

@app.route('/api/alertas')
def alertas():
    """Retorna domínios com alerta (próximos da expiração)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, situacao, created_at
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND situacao IN ('CRÍTICO', 'URGENTE', 'ATENÇÃO', 'EXPIRADO', 'EXPIRA_HOJE')
        ORDER BY 
            CASE situacao
                WHEN 'EXPIRADO' THEN 1
                WHEN 'EXPIRA_HOJE' THEN 2
                WHEN 'CRÍTICO' THEN 3
                WHEN 'URGENTE' THEN 4
                WHEN 'ATENÇÃO' THEN 5
            END,
            dias_para_expiracao ASC
    ''')
    
    alertas = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return jsonify(alertas)

@app.route('/api/stats')
def estatisticas():
    """Retorna estatísticas detalhadas"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Domínios por situação (últimas consultas)
    cursor.execute('''
        SELECT situacao, COUNT(*) as count
        FROM (
            SELECT situacao FROM dominios
            WHERE (dominio, created_at) IN (
                SELECT dominio, MAX(created_at)
                FROM dominios
                GROUP BY dominio
            )
        )
        GROUP BY situacao
    ''')
    
    por_situacao = [{'situacao': row['situacao'], 'count': row['count']} 
                    for row in cursor.fetchall()]
    
    # Evolução temporal (últimos 30 dias)
    cursor.execute('''
        SELECT DATE(created_at) as data, COUNT(*) as count
        FROM dominios
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY DATE(created_at)
        ORDER BY data
    ''')
    
    evolucao = [{'data': row['data'], 'count': row['count']} 
                for row in cursor.fetchall()]
    
    # Top 10 domínios mais consultados
    cursor.execute('''
        SELECT dominio, COUNT(*) as count
        FROM dominios
        GROUP BY dominio
        ORDER BY count DESC
        LIMIT 10
    ''')
    
    mais_consultados = [{'dominio': row['dominio'], 'count': row['count']} 
                        for row in cursor.fetchall()]
    
    conn.close()
    
    return jsonify({
        'por_situacao': por_situacao,
        'evolucao': evolucao,
        'mais_consultados': mais_consultados
    })


@app.route('/api/config/email', methods=['GET'])
def get_email_config():
    settings = get_web_settings()
    return jsonify(settings['email'])


@app.route('/api/config/email', methods=['POST'])
def set_email_config():
    payload = request.get_json(silent=True) or {}

    smtp_server = str(payload.get('smtp_server', '')).strip()
    remetente = str(payload.get('remetente', '')).strip()
    senha = payload.get('senha', '')
    destinatarios = _parse_recipients(payload.get('destinatarios', []))

    try:
        smtp_port = int(payload.get('smtp_port', 587))
    except Exception:
        return jsonify({'error': 'Porta SMTP inválida'}), 400

    if not smtp_server or not remetente or not destinatarios:
        return jsonify({'error': 'Preencha servidor SMTP, remetente e destinatários'}), 400

    settings = get_web_settings()
    settings['email']['smtp_server'] = smtp_server
    settings['email']['smtp_port'] = smtp_port
    settings['email']['remetente'] = remetente
    if str(senha).strip():
        settings['email']['senha'] = senha
    settings['email']['destinatarios'] = destinatarios

    save_web_settings(settings)
    apply_email_settings(settings['email'])
    return jsonify({'success': True})


@app.route('/api/config/schedule', methods=['GET'])
def get_schedule_config():
    settings = get_web_settings()
    return jsonify(settings['schedule'])


@app.route('/api/config/schedule', methods=['POST'])
def set_schedule_config():
    payload = request.get_json(silent=True) or {}

    recurrence = str(payload.get('recurrence', 'daily')).strip().lower()
    if recurrence not in ('daily', 'weekly', 'monthly'):
        return jsonify({'error': 'Recorrência inválida'}), 400

    time_value = str(payload.get('time', '08:00')).strip()
    if not _validate_time_str(time_value):
        return jsonify({'error': 'Hora inválida (use HH:MM)'}), 400

    try:
        day_of_week = int(payload.get('day_of_week', 0))
        day_of_month = int(payload.get('day_of_month', 1))
    except Exception:
        return jsonify({'error': 'Valores de dia inválidos'}), 400

    day_of_week = max(0, min(6, day_of_week))
    day_of_month = max(1, min(31, day_of_month))

    settings = get_web_settings()
    settings['schedule']['enabled'] = bool(payload.get('enabled', False))
    settings['schedule']['recurrence'] = recurrence
    settings['schedule']['time'] = time_value
    settings['schedule']['day_of_week'] = day_of_week
    settings['schedule']['day_of_month'] = day_of_month

    save_web_settings(settings)
    return jsonify({'success': True})


@app.route('/api/scheduler/run-now', methods=['POST'])
def scheduler_run_now():
    success = run_report_once()
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Falha ao enviar relatório'}), 500

if __name__ == '__main__':
    start_scheduler()
    apply_email_settings(get_web_settings()['email'])

    print("="*60)
    print("🌐 Interface Web RDAP Dashboard")
    print("="*60)
    print("\n✓ Servidor iniciando...")
    print("✓ Acesse: http://localhost:5000")
    print("✓ Scheduler de relatórios ativo")
    print("\n⚠️  Pressione CTRL+C para encerrar\n")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
