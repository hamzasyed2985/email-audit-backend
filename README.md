# Email Audit System

Automated email deliverability audit system that integrates with GlockApps, PostmarkApp, and Notion to analyze email reputation, authentication, and blacklist status.

## Features

- Automated blacklist checking for IPs and domains
- GlockApps email testing with seed lists
- PostmarkApp spam score analysis
- Google Postmaster Tools screenshot capture
- Notion database integration for audit management
- Error handling and logging

## Prerequisites

- Python 3.8+
- Notion workspace and API key
- GlockApps account and API key
- Blacklist Checker API key
- Google account with Postmaster Tools access

## Installation

### Clone and Setup

```bash
git clone https://github.com/yourusername/email-audit-backend.git
cd email-audit-backend
```

### Virtual Environment

```bash
python -m venv audit_env
audit_env\Scripts\activate  # Windows
source audit_env/bin/activate  # Linux/Mac
```

### Dependencies

```bash
pip install -r requirements.txt
playwright install
```

### Configuration

Copy `.env.example` to `.env` and add your credentials:

```env
NOTION_API_KEY="your_key"
NOTION_AUDITS_DB_ID="your_db_id"
GLOCKAPPS_API_KEY="your_key"
GLOCKAPPS_FOLDER_ID="your_folder_id"
GOOGLE_EMAIL="your_email"
GOOGLE_PASSWORD="your_password"
BLACKLIST_CHECKER_API_KEY="your_key"
```

### Notion Database Setup

Create a Notion database with these properties:
- Audit ID (Title)
- Domain (Relation)
- Audit Status (Select)
- Error Log (Rich Text)
- IP Blacklist Status (Rich Text)
- Domain Blacklist Status (Rich Text)
- GlockApps Test ID (Rich Text)

## Usage

Run the system:

```bash
python main.py
```

The system processes audits in the following order:
1. Blacklist checking (IP and domain)
2. GlockApps email test creation
3. Manual email sending step
4. GlockApps analysis
5. PostmarkApp spam analysis
6. Google Postmaster screenshot capture
7. Report generation in Notion

## Project Structure

```
├── main.py                   # Main orchestration
├── notion_manager.py         # Notion operations
├── blacklist_checker.py      # Blacklist verification
├── glockapps_api.py         # GlockApps integration
├── postmark_checker.py      # PostmarkApp integration
├── postmaster_scraper.py    # Postmaster scraping
├── report_generator.py      # Report generation
├── requirements.txt
└── Dockerfile
```

## Docker

```bash
docker build -t email-audit-system .
docker run -d --name audit-system --env-file .env email-audit-system
```

## Security

- Never commit `.env` file
- Use environment variables for credentials
- Rotate API keys regularly
- Use app-specific passwords for Google

## Contributing

Pull requests are welcome.

## License

MIT
