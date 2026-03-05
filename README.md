# Domain Explorer (DarkPan)

Painel web para monitoramento RDAP de domínios com interface baseada no tema oficial **DarkPan** (Bootstrap 5), além de relatório de e-mail no mesmo estilo visual dark.

## O que foi aplicado

- Interface Flask migrada para layout DarkPan completo:
  - Sidebar
  - Topbar sticky
  - Cards de métricas
  - Gráficos
  - Tabela de domínios
  - Lista de alertas
- Integração da UI com APIs existentes (`/api/*`) sem quebra de contrato.
- Relatório de e-mail (`consulta_whois_db.py`) atualizado para visual inspirado no DarkPan com CSS inline compatível com clientes de e-mail.
- Painel de configuração SMTP direto na interface web.
- Agendamento de envio de relatórios via interface:
  - Recorrência `daily`, `weekly` ou `monthly`
  - Definição de hora de envio
  - Disparo manual imediato de relatório
- Branding customizado com logo próprio no canto superior esquerdo e favicon.

## Estrutura principal

- `app.py`: servidor Flask e endpoints da API.
- `templates/index.html`: página principal em DarkPan.
- `static/darkpan/`: assets oficiais do tema (css/js/lib/img).
- `static/darkpan/js/rdap-main.js`: comportamento base da UI (spinner, sidebar, back-to-top).
- `static/darkpan/js/rdap-dashboard.js`: consumo das APIs e renderização dinâmica.
- `static/darkpan/css/rdap.css`: ajustes visuais específicos do Domain Explorer.
- `consulta_whois_db.py`: coleta RDAP e geração/envio de relatório HTML por e-mail.
- `web_settings.json`: persistência local da configuração de e-mail e agendamento (arquivo gerado em runtime).

## Como executar

1. Instale dependências Python (Flask e requests, se necessário).
2. Execute o painel web:

```bash
python app.py
```

3. Acesse:

- `http://localhost:5000`

## Endpoints usados pela interface

- `GET /api/dashboard`
- `GET /api/dominios`
- `GET /api/alertas`
- `GET /api/stats`
- `GET /api/dominio/<id>`
- `GET /api/exportar-csv`
- `GET /api/config/email`
- `POST /api/config/email`
- `GET /api/config/schedule`
- `POST /api/config/schedule`
- `POST /api/scheduler/run-now`

## Configuração de e-mail e agenda

- A configuração pode ser feita em `Email` e `Agendamento` dentro do dashboard.
- O backend salva as preferências em `web_settings.json`.
- O scheduler roda em background no processo Flask e verifica o horário configurado para envio.
- `web_settings.json` está no `.gitignore` para evitar versionar credenciais locais.

## Relatório de e-mail

As funções abaixo usam template HTML inline com paleta dark e contraste alto:

- `gerar_relatorio_email_teste()`
- `gerar_relatorio_email(conn)`

A estratégia prioriza compatibilidade em clientes como Gmail e Outlook.

## Créditos de tema

Tema base: DarkPan (HTML Codex / ThemeWagon)

- https://themewagon.com/themes/free-bootstrap-5-admin-dashboard-template-darkpan/
- https://themewagon.github.io/darkpan/
