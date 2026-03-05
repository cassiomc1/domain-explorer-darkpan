#!/usr/bin/env python3
"""
Script completo para consultar domínios usando RDAP via Who.is
Lê domínios do arquivo dominios_registro.txt (um por linha)
Armazena dados em banco SQLite com histórico completo
Envia relatório por email após as consultas
Funciona com qualquer TLD (.com, .br, .net, .org, etc)

Uso:
    python script.py                    # Execução normal
    python script.py --test-email       # Testa apenas o envio de email
"""

import requests
import json
from datetime import datetime
import sys
import os
import time
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
import csv
from io import StringIO

# ========== CONFIGURAÇÕES DE EMAIL ==========
# Edite estas configurações com suas credenciais
EMAIL_CONFIG = {
    'smtp_server': 'smtp.hostinger.com',  # Para Gmail
    'smtp_port': 587,
    'remetente': 'cassio@bytesec.pro',  # Seu email
    'senha': 'C4nt0n1@)!*',  # Senha de app do Gmail (não use sua senha normal)
    'destinatarios': ['cassio.campos@lucianoeisfeld.com','luciano@lucianoeisfeld.com'],  # Lista de emails para receber relatório
}

# Para Gmail, você precisa gerar uma "Senha de app":
# 1. Acesse: https://myaccount.google.com/security
# 2. Ative a verificação em duas etapas
# 3. Vá em "Senhas de app" e gere uma senha para "Email"
# 4. Use essa senha no campo 'senha' acima

def inicializar_banco():
    """
    Cria o banco de dados SQLite e as tabelas necessárias
    
    Returns:
        sqlite3.Connection: Conexão com o banco de dados
    """
    conn = sqlite3.connect('dominios_rdap.db')
    cursor = conn.cursor()
    
    # Tabela principal de domínios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dominios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio TEXT NOT NULL,
            handle TEXT,
            status TEXT,
            data_registro TEXT,
            data_expiracao TEXT,
            data_ultima_alteracao TEXT,
            dias_para_expiracao INTEGER,
            situacao TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(dominio, created_at)
        )
    ''')
    
    # Tabela de nameservers
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nameservers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio_id INTEGER,
            nome_ns TEXT,
            handle TEXT,
            ipv4 TEXT,
            ipv6 TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dominio_id) REFERENCES dominios(id)
        )
    ''')
    
    # Tabela de entidades (contatos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS entidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio_id INTEGER,
            handle TEXT,
            roles TEXT,
            nome_completo TEXT,
            tipo TEXT,
            organizacao TEXT,
            email TEXT,
            telefone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dominio_id) REFERENCES dominios(id)
        )
    ''')
    
    # Tabela de DNSSEC
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dnssec (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio_id INTEGER,
            delegacao_assinada BOOLEAN,
            zona_assinada BOOLEAN,
            key_tag INTEGER,
            algoritmo INTEGER,
            digest_type INTEGER,
            digest TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dominio_id) REFERENCES dominios(id)
        )
    ''')
    
    # Tabela de dados JSON completos (para preservar tudo)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dados_completos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio_id INTEGER,
            json_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dominio_id) REFERENCES dominios(id)
        )
    ''')
    
    # Tabela de histórico de status
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dominio TEXT NOT NULL,
            status_anterior TEXT,
            status_novo TEXT,
            dias_expiracao_anterior INTEGER,
            dias_expiracao_novo INTEGER,
            data_mudanca TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Índices para melhorar performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dominio ON dominios(dominio)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_expiracao ON dominios(data_expiracao)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_situacao ON dominios(situacao)')
    
    conn.commit()
    print("✓ Banco de dados inicializado: dominios_rdap.db\n")
    
    return conn

def consultar_dominio_rdap(dominio):
    """
    Consulta informações de um domínio via RDAP usando Who.is
    
    Args:
        dominio (str): Nome do domínio
    
    Returns:
        dict: Dicionário com as informações do domínio
    """
    dominio = dominio.replace('http://', '').replace('https://', '').replace('www.', '')
    dominio = dominio.split('/')[0]
    dominio = dominio.strip()
    
    # Detecta se é domínio .br para usar servidor específico
    if dominio.endswith('.br'):
        url_base = "https://rdap.registro.br/domain/"
    else:
        url_base = "https://rdap-bootstrap.arin.net/bootstrap/domain/"
    
    url = f"{url_base}{dominio}"
    
    try:
        headers = {
            'Accept': 'application/rdap+json',
            'User-Agent': 'Mozilla/5.0 (compatible; RDAP-Client/1.0)'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        dados = response.json()
        return dados
        
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Erro ao consultar o domínio: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"  ❌ Erro ao processar resposta JSON: {e}")
        return None

def ler_dominios_arquivo(arquivo):
    """
    Lê domínios do arquivo texto
    
    Args:
        arquivo (str): Caminho do arquivo
    
    Returns:
        list: Lista de domínios
    """
    if not os.path.exists(arquivo):
        print(f"❌ Erro: Arquivo '{arquivo}' não encontrado!")
        print(f"\nCrie o arquivo '{arquivo}' com um domínio por linha.")
        print("\nExemplo de conteúdo do arquivo:")
        print("  exemplo.com.br")
        print("  google.com")
        print("  github.com")
        return None
    
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            dominios = [linha.strip() for linha in f if linha.strip() and not linha.strip().startswith('#')]
        
        if not dominios:
            print(f"❌ Erro: Arquivo '{arquivo}' está vazio ou só contém comentários!")
            return None
        
        return dominios
    
    except Exception as e:
        print(f"❌ Erro ao ler arquivo '{arquivo}': {e}")
        return None

def formatar_data(data_str):
    """
    Formata data ISO 8601 para formato legível
    
    Args:
        data_str (str): Data em formato ISO 8601
    
    Returns:
        tuple: (datetime object, string formatada)
    """
    try:
        data = datetime.fromisoformat(data_str.replace('Z', '+00:00'))
        return data, data.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return None, data_str

def calcular_dias_restantes(data_expiracao):
    """
    Calcula quantos dias faltam para a expiração
    
    Args:
        data_expiracao (datetime): Data de expiração
    
    Returns:
        int: Número de dias restantes
    """
    if not isinstance(data_expiracao, datetime):
        return None
    agora = datetime.now(data_expiracao.tzinfo)
    delta = data_expiracao - agora
    return delta.days

def determinar_situacao(dias_restantes):
    """
    Determina a situação do domínio baseado nos dias restantes
    
    Args:
        dias_restantes (int): Dias até expiração
    
    Returns:
        str: Situação (OK, ATENÇÃO, URGENTE, CRÍTICO, EXPIRADO)
    """
    if dias_restantes is None:
        return 'DESCONHECIDO'
    elif dias_restantes < 0:
        return 'EXPIRADO'
    elif dias_restantes == 0:
        return 'EXPIRA_HOJE'
    elif dias_restantes <= 15:
        return 'CRÍTICO'
    elif dias_restantes <= 30:
        return 'URGENTE'
    elif dias_restantes <= 60:
        return 'ATENÇÃO'
    else:
        return 'OK'

def extrair_vcard(vcard_array):
    """
    Extrai informações do vCard
    
    Args:
        vcard_array (list): Array vCard
    
    Returns:
        dict: Informações extraídas
    """
    if not vcard_array or len(vcard_array) < 2:
        return {}
    
    vcard_data = vcard_array[1]
    info = {
        'nome_completo': None,
        'tipo': None,
        'organizacao': None,
        'emails': [],
        'telefones': []
    }
    
    for campo in vcard_data:
        if not campo or len(campo) < 2:
            continue
            
        tipo = campo[0]
        
        if tipo == 'fn':
            info['nome_completo'] = campo[3] if len(campo) > 3 else None
        elif tipo == 'kind':
            info['tipo'] = campo[3] if len(campo) > 3 else None
        elif tipo == 'org':
            info['organizacao'] = campo[3] if len(campo) > 3 else None
        elif tipo == 'tel':
            tel = campo[3] if len(campo) > 3 else None
            if tel:
                info['telefones'].append(tel)
        elif tipo == 'email':
            email = campo[3] if len(campo) > 3 else None
            if email:
                info['emails'].append(email)
    
    return info

def obter_status_anterior(conn, dominio):
    """
    Obtém o status mais recente do domínio
    
    Args:
        conn: Conexão com o banco
        dominio (str): Nome do domínio
    
    Returns:
        tuple: (status, dias_expiracao) ou (None, None)
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT status, dias_para_expiracao 
        FROM dominios 
        WHERE dominio = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    ''', (dominio,))
    
    resultado = cursor.fetchone()
    if resultado:
        return resultado[0], resultado[1]
    return None, None

def inserir_dominio(conn, dados, dominio_nome):
    """
    Insere dados do domínio no banco de dados
    
    Args:
        conn: Conexão com o banco
        dados (dict): Dados retornados pela API RDAP
        dominio_nome (str): Nome do domínio
    
    Returns:
        int: ID do domínio inserido
    """
    cursor = conn.cursor()
    
    # Extrai informações principais
    handle = dados.get('handle', '')
    status = ', '.join(dados.get('status', []))
    
    # Extrai datas dos eventos
    data_registro = None
    data_expiracao = None
    data_ultima_alteracao = None
    data_expiracao_obj = None
    
    if 'events' in dados:
        for evento in dados['events']:
            action = evento.get('eventAction')
            date_str = evento.get('eventDate')
            
            if date_str:
                data_obj, data_formatada = formatar_data(date_str)
                
                if action == 'registration':
                    data_registro = data_formatada
                elif action == 'expiration':
                    data_expiracao = data_formatada
                    data_expiracao_obj = data_obj
                elif action == 'last changed':
                    data_ultima_alteracao = data_formatada
    
    # Calcula dias para expiração
    dias_para_expiracao = calcular_dias_restantes(data_expiracao_obj) if data_expiracao_obj else None
    situacao = determinar_situacao(dias_para_expiracao)
    
    # Verifica mudança de status
    status_anterior, dias_anterior = obter_status_anterior(conn, dominio_nome)
    
    if status_anterior and (status_anterior != status or dias_anterior != dias_para_expiracao):
        cursor.execute('''
            INSERT INTO historico_status 
            (dominio, status_anterior, status_novo, dias_expiracao_anterior, dias_expiracao_novo)
            VALUES (?, ?, ?, ?, ?)
        ''', (dominio_nome, status_anterior, status, dias_anterior, dias_para_expiracao))
        print(f"  📊 Mudança detectada - Status: {status_anterior} → {status}")
    
    # Insere domínio
    cursor.execute('''
        INSERT INTO dominios 
        (dominio, handle, status, data_registro, data_expiracao, data_ultima_alteracao, 
         dias_para_expiracao, situacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (dominio_nome, handle, status, data_registro, data_expiracao, data_ultima_alteracao,
          dias_para_expiracao, situacao))
    
    dominio_id = cursor.lastrowid
    
    # Insere nameservers
    if 'nameservers' in dados:
        for ns in dados['nameservers']:
            nome_ns = ns.get('ldhName', '')
            handle_ns = ns.get('handle', '')
            status_ns = ', '.join(ns.get('status', []))
            
            ipv4 = ', '.join(ns.get('ipAddresses', {}).get('v4', [])) if 'ipAddresses' in ns else ''
            ipv6 = ', '.join(ns.get('ipAddresses', {}).get('v6', [])) if 'ipAddresses' in ns else ''
            
            cursor.execute('''
                INSERT INTO nameservers 
                (dominio_id, nome_ns, handle, ipv4, ipv6, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (dominio_id, nome_ns, handle_ns, ipv4, ipv6, status_ns))
    
    # Insere entidades
    if 'entities' in dados:
        for entidade in dados['entities']:
            handle_ent = entidade.get('handle', '')
            roles = ', '.join(entidade.get('roles', []))
            
            vcard_info = {}
            if 'vcardArray' in entidade:
                vcard_info = extrair_vcard(entidade['vcardArray'])
            
            nome_completo = vcard_info.get('nome_completo', '')
            tipo = vcard_info.get('tipo', '')
            organizacao = vcard_info.get('organizacao', '')
            email = ', '.join(vcard_info.get('emails', []))
            telefone = ', '.join(vcard_info.get('telefones', []))
            
            cursor.execute('''
                INSERT INTO entidades 
                (dominio_id, handle, roles, nome_completo, tipo, organizacao, email, telefone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (dominio_id, handle_ent, roles, nome_completo, tipo, organizacao, email, telefone))
    
    # Insere DNSSEC
    if 'secureDNS' in dados:
        secure_dns = dados['secureDNS']
        delegacao = secure_dns.get('delegationSigned', False)
        zona = secure_dns.get('zoneSigned', False)
        
        if 'dsData' in secure_dns:
            for ds in secure_dns['dsData']:
                cursor.execute('''
                    INSERT INTO dnssec 
                    (dominio_id, delegacao_assinada, zona_assinada, key_tag, algoritmo, digest_type, digest)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (dominio_id, delegacao, zona, ds.get('keyTag'), ds.get('algorithm'),
                      ds.get('digestType'), ds.get('digest')))
        else:
            # Insere registro mesmo sem DS data
            cursor.execute('''
                INSERT INTO dnssec 
                (dominio_id, delegacao_assinada, zona_assinada, key_tag, algoritmo, digest_type, digest)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL)
            ''', (dominio_id, delegacao, zona))
    
    # Salva JSON completo
    json_data = json.dumps(dados, ensure_ascii=False)
    cursor.execute('''
        INSERT INTO dados_completos (dominio_id, json_data)
        VALUES (?, ?)
    ''', (dominio_id, json_data))
    
    conn.commit()
    
    return dominio_id

def gerar_relatorio_email_teste():
    """
    Gera relatório de teste para verificar envio de email
    
    Returns:
        str: HTML de teste
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Teste de Email - RDAP</title>
    </head>
    <body style="margin:0;padding:0;background:#000000;font-family:Arial,sans-serif;color:#ffffff;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000000;padding:24px 12px;">
            <tr>
                <td align="center">
                    <table role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:760px;background:#191c24;border:1px solid #2c2f3a;border-radius:10px;overflow:hidden;">
                        <tr>
                            <td style="background:#191c24;border-bottom:3px solid #eb1616;padding:24px;">
                                <h1 style="margin:0;font-size:24px;line-height:1.2;color:#ffffff;">Teste de Email - Sistema RDAP</h1>
                                <p style="margin:8px 0 0;color:#b8bac4;font-size:14px;">Enviado em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:20px 24px;">
                                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#111318;border:1px solid #2c2f3a;border-radius:8px;">
                                    <tr>
                                        <td style="padding:18px;">
                                            <p style="margin:0 0 10px;font-size:18px;color:#16c47f;font-weight:bold;">Configuração de email funcionando</p>
                                            <p style="margin:0;color:#b8bac4;line-height:1.5;">Se você recebeu esta mensagem, o envio SMTP está operacional.</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:0 24px 20px;">
                                <h2 style="margin:0 0 10px;font-size:18px;color:#ffffff;">Informações do teste</h2>
                                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:#111318;border:1px solid #2c2f3a;">
                                    <tr><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#9ca3af;width:220px;">Data/Hora</td><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#ffffff;">{datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</td></tr>
                                    <tr><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#9ca3af;">Servidor SMTP</td><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#ffffff;">{EMAIL_CONFIG['smtp_server']}</td></tr>
                                    <tr><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#9ca3af;">Porta</td><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#ffffff;">{EMAIL_CONFIG['smtp_port']}</td></tr>
                                    <tr><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#9ca3af;">Remetente</td><td style="padding:10px;border-bottom:1px solid #2c2f3a;color:#ffffff;">{EMAIL_CONFIG['remetente']}</td></tr>
                                    <tr><td style="padding:10px;color:#9ca3af;">Destinatários</td><td style="padding:10px;color:#ffffff;">{', '.join(EMAIL_CONFIG['destinatarios'])}</td></tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:0 24px 24px;">
                                <p style="margin:0;color:#6c7293;font-size:13px;line-height:1.5;">Este é um email automático de teste do monitoramento RDAP.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    return html

def gerar_relatorio_email(conn):
    """
    Gera relatório HTML para envio por email
    
    Args:
        conn: Conexão com o banco
    
    Returns:
        tuple: (html_content, tem_alertas)
    """
    cursor = conn.cursor()
    
    # Busca domínios por categoria
    categorias = {
        'expirados': [],
        '15_dias': [],
        '30_dias': [],
        '60_dias': []
    }
    
    # Domínios expirados
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, status
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND dias_para_expiracao < 0
        ORDER BY dias_para_expiracao ASC
    ''')
    categorias['expirados'] = cursor.fetchall()
    
    # Próximos 15 dias
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, status
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND dias_para_expiracao >= 0 AND dias_para_expiracao <= 15
        ORDER BY dias_para_expiracao ASC
    ''')
    categorias['15_dias'] = cursor.fetchall()
    
    # Próximos 30 dias
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, status
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND dias_para_expiracao > 15 AND dias_para_expiracao <= 30
        ORDER BY dias_para_expiracao ASC
    ''')
    categorias['30_dias'] = cursor.fetchall()
    
    # Próximos 60 dias
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, status
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND dias_para_expiracao > 30 AND dias_para_expiracao <= 60
        ORDER BY dias_para_expiracao ASC
    ''')
    categorias['60_dias'] = cursor.fetchall()
    
    # Verifica se há alertas
    tem_alertas = any(len(v) > 0 for v in categorias.values())
    
    def render_categoria(titulo, dados, borda, badge_bg, badge_fg, expirado=False):
        bloco = f"""
        <tr>
            <td style="padding:0 24px 16px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:#111318;border:1px solid #2c2f3a;border-left:4px solid {borda};border-radius:8px;overflow:hidden;">
                    <tr>
                        <td style="padding:14px 14px 10px;font-size:16px;font-weight:bold;color:#ffffff;">{titulo}</td>
                    </tr>
        """

        if dados:
            bloco += """
                    <tr>
                        <td style="padding:0 14px 14px;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
                                <tr>
                                    <th style="text-align:left;padding:10px;color:#9ca3af;border-bottom:1px solid #2c2f3a;font-size:12px;">DOMÍNIO</th>
                                    <th style="text-align:left;padding:10px;color:#9ca3af;border-bottom:1px solid #2c2f3a;font-size:12px;">EXPIRAÇÃO</th>
                                    <th style="text-align:left;padding:10px;color:#9ca3af;border-bottom:1px solid #2c2f3a;font-size:12px;">DIAS</th>
                                    <th style="text-align:left;padding:10px;color:#9ca3af;border-bottom:1px solid #2c2f3a;font-size:12px;">STATUS</th>
                                </tr>
            """

            for dom in dados:
                dias_texto = f"{abs(dom[2])} dias atrás" if expirado else f"{dom[2]} dias"
                bloco += f"""
                                <tr>
                                    <td style="padding:10px;color:#ffffff;border-bottom:1px solid #2c2f3a;"><strong>{dom[0]}</strong></td>
                                    <td style="padding:10px;color:#d4d7e2;border-bottom:1px solid #2c2f3a;">{dom[1]}</td>
                                    <td style="padding:10px;border-bottom:1px solid #2c2f3a;">
                                        <span style="display:inline-block;padding:4px 8px;border-radius:4px;background:{badge_bg};color:{badge_fg};font-size:12px;font-weight:bold;">{dias_texto}</span>
                                    </td>
                                    <td style="padding:10px;color:#d4d7e2;border-bottom:1px solid #2c2f3a;">{dom[3]}</td>
                                </tr>
                """

            bloco += """
                            </table>
                        </td>
                    </tr>
            """
        else:
            bloco += """
                    <tr>
                        <td style="padding:0 14px 14px;">
                            <div style="padding:12px;border-radius:6px;background:#0f2f22;color:#16c47f;font-weight:bold;text-align:center;">Nenhum domínio nesta categoria.</div>
                        </td>
                    </tr>
            """

        bloco += """
                </table>
            </td>
        </tr>
        """
        return bloco

    total = sum(len(v) for v in categorias.values())

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Relatório RDAP</title>
    </head>
    <body style="margin:0;padding:0;background:#000000;font-family:Arial,sans-serif;color:#ffffff;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000000;padding:24px 12px;">
            <tr>
                <td align="center">
                    <table role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:760px;background:#191c24;border:1px solid #2c2f3a;border-radius:10px;overflow:hidden;">
                        <tr>
                            <td style="background:#191c24;border-bottom:3px solid #eb1616;padding:24px;">
                                <h1 style="margin:0;font-size:24px;line-height:1.2;color:#ffffff;">Relatório de Domínios RDAP</h1>
                                <p style="margin:8px 0 0;color:#b8bac4;font-size:14px;">Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:20px 24px;">
                                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:#111318;border:1px solid #2c2f3a;border-radius:8px;">
                                    <tr>
                                        <td style="padding:14px;color:#ffffff;font-size:15px;">
                                            <strong>Total de domínios com atenção necessária:</strong> {total}<br>
                                            <span style="color:#9ca3af;font-size:13px;">Expirados: {len(categorias['expirados'])} | 0-15 dias: {len(categorias['15_dias'])} | 16-30 dias: {len(categorias['30_dias'])} | 31-60 dias: {len(categorias['60_dias'])}</span>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        {render_categoria('DOMÍNIOS EXPIRADOS', categorias['expirados'], '#eb1616', '#eb1616', '#ffffff', expirado=True)}
                        {render_categoria('CRÍTICO - Expiram em até 15 dias', categorias['15_dias'], '#dc2626', '#dc2626', '#ffffff')}
                        {render_categoria('URGENTE - Expiram em 16-30 dias', categorias['30_dias'], '#f59e0b', '#f59e0b', '#111111')}
                        {render_categoria('ATENÇÃO - Expiram em 31-60 dias', categorias['60_dias'], '#facc15', '#facc15', '#111111')}
                        <tr>
                            <td style="padding:0 24px 24px;">
                                <p style="margin:0;color:#6c7293;font-size:13px;line-height:1.5;">Relatório automático gerado pelo monitoramento RDAP. Para análises detalhadas, acesse o dashboard web.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    return html, tem_alertas

def enviar_email_relatorio(html_content, tem_alertas, modo_teste=False):
    """
    Envia relatório por email
    
    Args:
        html_content (str): Conteúdo HTML do email
        tem_alertas (bool): Se há alertas no relatório
        modo_teste (bool): Se é um email de teste
    """
    try:
        # Verifica se as configurações estão preenchidas
        if EMAIL_CONFIG['remetente'] == 'seu_email@gmail.com':
            print("\n⚠️  Configurações de email não foram definidas!")
            print("   Edite as configurações EMAIL_CONFIG no início do script.")
            print("   Relatório NÃO foi enviado por email.\n")
            return False
        
        # Cria mensagem
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_CONFIG['remetente']
        msg['To'] = ', '.join(EMAIL_CONFIG['destinatarios'])
        
        # Define assunto baseado no modo e alertas
        if modo_teste:
            assunto = f"✅ TESTE - Sistema RDAP - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        elif tem_alertas:
            assunto = f"⚠️ ALERTA - Relatório de Domínios RDAP - {datetime.now().strftime('%d/%m/%Y')}"
        else:
            assunto = f"✅ Relatório de Domínios RDAP - {datetime.now().strftime('%d/%m/%Y')}"

        msg['Subject'] = str(Header(assunto, 'utf-8'))
        
        # Anexa HTML
        parte_html = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(parte_html)
        
        # Conecta e envia
        print("\n📧 Enviando email...")
        print(f"   Servidor: {EMAIL_CONFIG['smtp_server']}:{EMAIL_CONFIG['smtp_port']}")
        print(f"   De: {EMAIL_CONFIG['remetente']}")
        print(f"   Para: {', '.join(EMAIL_CONFIG['destinatarios'])}")
        
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['remetente'], EMAIL_CONFIG['senha'])
            server.send_message(msg)
        
        print(f"\n✅ Email enviado com sucesso!")
        if modo_teste:
            print("   Verifique sua caixa de entrada para confirmar o recebimento.")
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("\n❌ Erro de autenticação no servidor de email!")
        print("   Verifique:")
        print("   - Email está correto")
        print("   - Para Gmail, use senha de app (não a senha normal)")
        print("   - Acesse: https://myaccount.google.com/security")
        return False
    except Exception as e:
        print(f"\n❌ Erro ao enviar email: {e}")
        return False

def testar_email():
    """
    Modo de teste de email
    """
    print("="*80)
    print("MODO DE TESTE DE EMAIL")
    print("="*80)
    print("\nEste modo envia apenas um email de teste para verificar as configurações.\n")
    
    print("Configurações atuais:")
    print(f"  Servidor SMTP: {EMAIL_CONFIG['smtp_server']}:{EMAIL_CONFIG['smtp_port']}")
    print(f"  Remetente: {EMAIL_CONFIG['remetente']}")
    print(f"  Destinatários: {', '.join(EMAIL_CONFIG['destinatarios'])}")
    
    if EMAIL_CONFIG['remetente'] == 'seu_email@gmail.com':
        print("\n⚠️  ATENÇÃO: Você precisa configurar o email antes de testar!")
        print("\nEdite as seguintes variáveis no início do script:")
        print("  EMAIL_CONFIG['remetente'] = 'seu_email@gmail.com'")
        print("  EMAIL_CONFIG['senha'] = 'sua_senha_app'")
        print("  EMAIL_CONFIG['destinatarios'] = ['destino@example.com']")
        print("\nPara Gmail, gere uma senha de app em:")
        print("  https://myaccount.google.com/security")
        return
    
    print("\n" + "-"*80)
    resposta = input("\nDeseja enviar um email de teste? (s/n): ").lower().strip()
    
    if resposta == 's':
        print("\n" + "="*80)
        print("Gerando email de teste...")
        
        html_content = gerar_relatorio_email_teste()
        sucesso = enviar_email_relatorio(html_content, tem_alertas=False, modo_teste=True)
        
        if sucesso:
            print("\n" + "="*80)
            print("✅ TESTE CONCLUÍDO COM SUCESSO!")
            print("="*80)
            print("\nO email de teste foi enviado.")
            print("Verifique sua caixa de entrada (e spam) nos destinatários configurados.")
            print("\nSe recebeu o email, a configuração está correta!")
            print("Agora você pode executar o script normalmente: python script.py")
        else:
            print("\n" + "="*80)
            print("❌ TESTE FALHOU")
            print("="*80)
            print("\nRevise as configurações e tente novamente.")
    else:
        print("\nTeste cancelado.")

def exibir_resumo_db(conn):
    """
    Exibe resumo dos dados no banco
    
    Args:
        conn: Conexão com o banco
    """
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("RESUMO DO BANCO DE DADOS")
    print("="*80)
    
    # Total de registros
    cursor.execute('SELECT COUNT(*) FROM dominios')
    total = cursor.fetchone()[0]
    print(f"\nTotal de consultas armazenadas: {total}")
    
    # Domínios únicos
    cursor.execute('SELECT COUNT(DISTINCT dominio) FROM dominios')
    unicos = cursor.fetchone()[0]
    print(f"Domínios únicos: {unicos}")
    
    # Por situação
    print("\nDistribuição por situação:")
    cursor.execute('''
        SELECT situacao, COUNT(*) 
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
        ORDER BY 
            CASE situacao
                WHEN 'EXPIRADO' THEN 1
                WHEN 'EXPIRA_HOJE' THEN 2
                WHEN 'CRÍTICO' THEN 3
                WHEN 'URGENTE' THEN 4
                WHEN 'ATENÇÃO' THEN 5
                WHEN 'OK' THEN 6
                ELSE 7
            END
    ''')
    
    situacoes = cursor.fetchall()
    emoji_map = {
        'EXPIRADO': '⚠️',
        'EXPIRA_HOJE': '⚠️',
        'CRÍTICO': '🔴',
        'URGENTE': '🟠',
        'ATENÇÃO': '🟡',
        'OK': '🟢',
        'DESCONHECIDO': '⚪'
    }
    
    for situacao, count in situacoes:
        emoji = emoji_map.get(situacao, '•')
        print(f"  {emoji} {situacao}: {count}")
    
    # Domínios próximos da expiração (últimas consultas)
    print("\nDomínios que expiram em breve (últimas consultas):")
    cursor.execute('''
        SELECT dominio, data_expiracao, dias_para_expiracao, situacao
        FROM dominios
        WHERE (dominio, created_at) IN (
            SELECT dominio, MAX(created_at)
            FROM dominios
            GROUP BY dominio
        )
        AND dias_para_expiracao IS NOT NULL
        AND dias_para_expiracao <= 60
        ORDER BY dias_para_expiracao ASC
        LIMIT 10
    ''')
    
    proximos = cursor.fetchall()
    if proximos:
        for dom, exp, dias, sit in proximos:
            emoji = emoji_map.get(sit, '•')
            print(f"  {emoji} {dom}: {dias} dias ({exp})")
    else:
        print("  Nenhum domínio próximo da expiração")
    
    # Mudanças recentes
    cursor.execute('SELECT COUNT(*) FROM historico_status')
    mudancas = cursor.fetchone()[0]
    if mudancas > 0:
        print(f"\nTotal de mudanças de status detectadas: {mudancas}")
        
        cursor.execute('''
            SELECT dominio, status_anterior, status_novo, data_mudanca
            FROM historico_status
            ORDER BY data_mudanca DESC
            LIMIT 5
        ''')
        
        print("Últimas 5 mudanças:")
        for dom, ant, novo, data in cursor.fetchall():
            print(f"  • {dom}: {ant} → {novo} ({data})")
    
    print("\n" + "="*80)

def exibir_ajuda():
    """Exibe ajuda de uso do script"""
    print("""
Uso: python script.py [opções]

Opções:
    (sem opções)          Executa consulta normal de domínios e envia relatório
    --test-email          Testa apenas o envio de email (não faz consultas)
    --help, -h            Exibe esta mensagem de ajuda

Exemplos:
    python script.py                    # Consulta domínios e envia relatório
    python script.py --test-email       # Envia email de teste
    python script.py dominios.txt       # Usa arquivo customizado

Configuração de Email:
    Edite as variáveis EMAIL_CONFIG no início do script antes de usar.
    Para Gmail, use senha de app: https://myaccount.google.com/security
    """)

def main():
    """Função principal"""
    
    # Verifica argumentos
    if '--help' in sys.argv or '-h' in sys.argv:
        exibir_ajuda()
        sys.exit(0)
    
    # Modo de teste de email
    if '--test-email' in sys.argv:
        testar_email()
        sys.exit(0)
    
    # Execução normal
    arquivo_dominios = 'dominios_registro.txt'
    
    print("="*80)
    print("Script de Consulta RDAP com Banco de Dados SQLite e Email")
    print("="*80)
    
    # Inicializa banco de dados
    conn = inicializar_banco()
    
    # Verifica argumentos opcionais
    arquivo_custom = None
    
    for arg in sys.argv[1:]:
        if arg.endswith('.txt') and not arg.startswith('-'):
            arquivo_custom = arg
            break
    
    if arquivo_custom:
        arquivo_dominios = arquivo_custom
    
    print(f"📄 Lendo domínios de: {arquivo_dominios}")
    
    # Lê domínios do arquivo
    dominios = ler_dominios_arquivo(arquivo_dominios)
    
    if not dominios:
        print("\n💡 Dica: Crie o arquivo com o seguinte formato:")
        print("   exemplo.com.br")
        print("   google.com")
        print("   github.com")
        conn.close()
        sys.exit(1)
    
    total = len(dominios)
    print(f"✓ {total} domínio(s) encontrado(s)\n")
    print("="*80)
    
    sucesso = 0
    falhas = 0
    
    # Processa cada domínio
    for idx, dominio in enumerate(dominios, 1):
        print(f"\n[{idx}/{total}] 🔍 Consultando: {dominio}")
        
        # Consulta o domínio
        dados = consultar_dominio_rdap(dominio)
        
        if dados:
            try:
                # Insere no banco de dados
                dominio_id = inserir_dominio(conn, dados, dominio)
                sucesso += 1
                
                # Exibe resumo
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT status, data_expiracao, dias_para_expiracao, situacao
                    FROM dominios WHERE id = ?
                ''', (dominio_id,))
                
                info = cursor.fetchone()
                if info:
                    print(f"  Status: {info[0]}")
                    if info[1]:
                        print(f"  Expira em: {info[1]}")
                        if info[2] is not None:
                            dias = info[2]
                            if dias < 0:
                                print(f"  ⚠️  EXPIRADO há {abs(dias)} dias!")
                            elif dias <= 15:
                                print(f"  🔴 CRÍTICO: {dias} dias restantes")
                            elif dias <= 30:
                                print(f"  🟠 URGENTE: {dias} dias restantes")
                            elif dias <= 60:
                                print(f"  🟡 ATENÇÃO: {dias} dias restantes")
                            else:
                                print(f"  🟢 OK: {dias} dias restantes")
                    else:
                        print(f"  ⚠️  Data de expiração não encontrada")
                
                print(f"  ✓ Dados inseridos no banco (ID: {dominio_id})")
                
            except Exception as e:
                print(f"  ❌ Erro ao inserir no banco: {e}")
                falhas += 1
        else:
            falhas += 1
        
        # Delay entre requisições
        if idx < total:
            time.sleep(0.5)
    
    # Sumário final
    print("\n" + "="*80)
    print("SUMÁRIO DA EXECUÇÃO")
    print("="*80)
    print(f"Total de domínios: {total}")
    print(f"✓ Consultas bem-sucedidas: {sucesso}")
    print(f"✗ Falhas: {falhas}")
    
    # Exibe resumo do banco
    exibir_resumo_db(conn)
    
    # Gera e envia relatório por email
    print("\n" + "="*80)
    print("GERANDO RELATÓRIO DE EMAIL")
    print("="*80)
    
    html_content, tem_alertas = gerar_relatorio_email(conn)
    
    if tem_alertas:
        print("\n⚠️  ALERTAS DETECTADOS - Domínios precisam de atenção!")
    else:
        print("\n✅ Todos os domínios estão OK!")
    
    enviar_email_relatorio(html_content, tem_alertas, modo_teste=False)
    
    print("\n✓ Processamento concluído!")
    print("✓ Banco de dados: dominios_rdap.db")
    print("="*80 + "\n")
    
    conn.close()

if __name__ == "__main__":
    main()
