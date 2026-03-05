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
from io import StringIO

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

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
    
    return Response(
        output.getvalue(),
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

if __name__ == '__main__':
    print("="*60)
    print("🌐 Interface Web RDAP Dashboard")
    print("="*60)
    print("\n✓ Servidor iniciando...")
    print("✓ Acesse: http://localhost:5000")
    print("\n⚠️  Pressione CTRL+C para encerrar\n")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
