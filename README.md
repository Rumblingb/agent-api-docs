# Jack's Agent API

Structured JSON APIs for AI agents. No web scraping needed.

## Endpoints
- POST /api/format/json — Format and validate JSON
- POST /api/count/tokens — Count tokens for AI models
- POST /api/generate/qr — Generate QR codes
- POST /api/generate/palette — Color palette generator
- POST /api/domain/history — Domain history (Wayback Machine)
- POST /api/decode/jwt — Decode JWT tokens
- POST /api/keys/register — Get free API key

## Pricing
- Free: 100 requests/day
- Pro: $9/mo unlimited — https://buy.stripe.com/aFaaEZ0qX97Se6cfrt1oI0j

## Deploy
```bash
uvicorn server:app --host 0.0.0.0 --port 8080
```

Docs: https://rumblingb.github.io/agent-api-docs/
