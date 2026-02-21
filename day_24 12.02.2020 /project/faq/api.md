# API FAQ

## Authentication

All API requests require authentication using an API key. Include your API key in the Authorization header: `Authorization: Bearer YOUR_API_KEY`. You can generate and manage API keys from Settings > API Keys. Each API key has configurable scopes and can be revoked at any time.

## Rate Limits

API rate limits depend on your plan. Free plan: 50 requests per minute. Pro plan: 500 requests per minute. Enterprise plan: unlimited (fair use policy applies). When you exceed your rate limit, the API returns HTTP 429 Too Many Requests with a Retry-After header indicating how long to wait.

## Error Codes

Common API error codes: 400 Bad Request (invalid parameters), 401 Unauthorized (missing or invalid API key), 403 Forbidden (insufficient permissions), 404 Not Found (resource does not exist), 429 Too Many Requests (rate limit exceeded), 500 Internal Server Error (server-side issue, contact support).

## Webhook Setup

To configure webhooks, go to Settings > Webhooks > Add Endpoint. Enter your HTTPS endpoint URL and select the events you want to receive. We support events for tickets, users, and billing. Webhook payloads are signed with your webhook secret for verification. Failed deliveries are retried up to 5 times with exponential backoff.

## Webhook Troubleshooting

If your webhook endpoint is not receiving events, verify that: your endpoint returns HTTP 200 within 30 seconds, the URL is publicly accessible, your firewall allows traffic from our IP ranges, and the webhook is enabled in your settings. Check the webhook delivery log in Settings > Webhooks > Delivery Log for error details.

## SDKs and Libraries

We provide official SDKs for Python, JavaScript, Go, and Ruby. SDKs are available on their respective package managers (pip, npm, go get, gem). Each SDK includes automatic retry logic, rate limit handling, and type-safe request/response objects. Documentation and examples are available in the SDK repositories.

## API Versioning

Our API uses date-based versioning. The current version is 2025-01-15. Specify the version using the API-Version header. Breaking changes are only introduced in new versions. We maintain backward compatibility for at least 12 months after a new version is released.

## API Key Rotation

For security, we recommend rotating your API keys every 90 days. You can create a new key before revoking the old one to ensure zero downtime. Enterprise customers can automate key rotation using the Key Management API endpoint.
