# API tokens for the Telegram GPT bot
# Copy this file to config.py and fill in your API tokens

api_token_telegram = "YOUR_TELEGRAM_BOT_TOKEN"
api_token_openai = "YOUR_OPENAI_API_KEY"

# Perplexity API key for MCP Server integration
# Get your API key from https://www.perplexity.ai/settings/api
api_token_perplexity = "YOUR_PERPLEXITY_API_KEY"

# Yandex Calendar integration (CalDAV)
# Create an app password at https://id.yandex.ru/security/app-passwords
# Select "Calendar" as the application type
yandex_calendar_username = ""  # Your Yandex email (e.g., user@yandex.ru)
yandex_calendar_password = ""  # App password (NOT your main password)

# Yandex Mail SMTP integration (for email notifications)
# Uses the same Yandex account as calendar
# Create an app password at https://id.yandex.ru/security/app-passwords
# Select "Mail" as the application type
#
# For Kubernetes: set via environment variables (see k8s/secrets.yaml)
# For local development: set these values OR use environment variables
yandex_smtp_email = ""      # Your Yandex email (e.g., user@yandex.ru)
yandex_smtp_password = ""   # App password for Mail (NOT your main password)
