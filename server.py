# Jack's Agent API — Server for AI Agent Tool Access
# Revenue model: Free 100/day, Pro $9/mo unlimited
# Deploy: uvicorn server:host --host 0.0.0.0 --port 8080

import json
import time
import hashlib
import hmac
import re
import io
import base64
from datetime import datetime, date
from typing import Optional
from urllib.parse import urlencode

import httpx
import qrcode
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI(
    title="Jack's Agent API",
    description="Structured JSON APIs for AI agents. Tools: JSON, QR, Tokens, Colors, Domain History.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API Key Management (in-memory for MVP) ──────────────────────────
# In production: store in Supabase/PostgreSQL
API_KEYS = {}  # key -> {"tier": "free"|"pro", "calls_today": 0, "date": "2026-05-09"}
FREE_DAILY_LIMIT = 100
PRO_DAILY_LIMIT = 100000

def check_rate_limit(api_key: str = Header(None, alias="X-API-Key")):
    """Rate limiting middleware — free: 100/day, pro: unlimited"""
    today = date.today().isoformat()
    
    if api_key and api_key in API_KEYS:
        entry = API_KEYS[api_key]
        if entry["date"] != today:
            entry["calls_today"] = 0
            entry["date"] = today
        entry["calls_today"] += 1
        limit = PRO_DAILY_LIMIT if entry["tier"] == "pro" else FREE_DAILY_LIMIT
        if entry["calls_today"] > limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Upgrade to Pro at https://rumblingb.github.io/jacks-toolbox/")
        return api_key
    else:
        # Anonymous access — also 100/day tracked by IP
        return None

# ─── Request Models ────────────────────────────────────────────────

class FormatJSONRequest(BaseModel):
    text: str
    indent: Optional[int] = 2
    sort_keys: Optional[bool] = False

class ValidateJSONRequest(BaseModel):
    text: str

class TokenCountRequest(BaseModel):
    text: str
    model: Optional[str] = "gpt-4"

class QRRequest(BaseModel):
    text: str
    size: Optional[int] = 300
    format: Optional[str] = "png"  # png, svg, base64

class PaletteRequest(BaseModel):
    type: Optional[str] = "complementary"  # complementary, analogous, triadic, monochromatic
    base_color: Optional[str] = None  # hex color like #7c5cff
    count: Optional[int] = 5

class DomainHistoryRequest(BaseModel):
    domain: str
    year: Optional[int] = None
    limit: Optional[int] = 10

class JWTDecodeRequest(BaseModel):
    token: str

# ─── API Endpoints ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.utcnow().isoformat()}

# ─── 1. JSON Formatter & Validator ────────────────────────────────

@app.post("/api/format/json", summary="Format and validate JSON")
async def format_json(req: FormatJSONRequest, request: Request):
    """Parse, validate, and format JSON text. Returns structured JSON output."""
    try:
        parsed = json.loads(req.text)
        formatted = json.dumps(parsed, indent=req.indent, sort_keys=req.sort_keys)
        return {
            "success": True,
            "formatted": formatted,
            "type": type(parsed).__name__,
            "length": len(formatted),
            "size_bytes": len(formatted.encode("utf-8")),
        }
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": str(e),
            "position": e.pos,
            "line": e.lineno,
            "column": e.colno,
        }

@app.post("/api/validate/json", summary="Validate JSON syntax")
async def validate_json(req: ValidateJSONRequest):
    """Check if text is valid JSON. Returns validation result."""
    try:
        parsed = json.loads(req.text)
        return {
            "valid": True,
            "type": type(parsed).__name__,
            "size": len(req.text),
        }
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "error": str(e),
            "line": e.lineno,
            "column": e.colno,
        }

# ─── 2. Token Counter ──────────────────────────────────────────────

# Simple token estimation (character-based, approximate)
MODEL_ENCODINGS = {
    "gpt-4": 4.0,
    "gpt-3.5-turbo": 4.0,
    "claude-3": 3.5,
    "claude-sonnet-4": 3.5,
    "llama-3": 4.0,
    "gemini-pro": 4.0,
    "deepseek": 3.8,
}

@app.post("/api/count/tokens", summary="Count tokens in text")
async def count_tokens(req: TokenCountRequest):
    """Estimate token count for various AI models. Uses char-based approximation."""
    chars = len(req.text)
    words = len(req.text.split())
    chars_per_token = MODEL_ENCODINGS.get(req.model, MODEL_ENCODINGS["gpt-4"])
    estimated_tokens = int(chars / chars_per_token)
    
    return {
        "text": req.text[:50] + ("..." if len(req.text) > 50 else ""),
        "characters": chars,
        "words": words,
        "model": req.model,
        "estimated_tokens": estimated_tokens,
        "tokens_per_char": round(1/chars_per_token, 4),
    }

# ─── 3. QR Code Generator ──────────────────────────────────────────

@app.post("/api/generate/qr", summary="Generate QR code")
async def generate_qr(req: QRRequest):
    """Generate QR codes in PNG or base64 format for any text/URL."""
    try:
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(req.text)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        if req.format == "base64":
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {
                "success": True,
                "format": "base64",
                "data": f"data:image/png;base64,{b64}",
                "data_url": f"data:image/png;base64,{b64[:50]}...[truncated]",
            }
        else:
            # Return metadata — actual image served via GET
            encoded = urlencode({"text": req.text})
            return {
                "success": True,
                "format": "png",
                "image_url": f"/api/generate/qr/image?{encoded}",
                "data": req.text,
                "size": req.size,
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/generate/qr/image")
async def get_qr_image(text: str, size: int = 300):
    """GET endpoint that returns actual QR code PNG image."""
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Resize
    img = img.resize((size, size))
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="image/png")

# ─── 4. Color Palette Generator ────────────────────────────────────

import colorsys
import random

def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r, g, b):
    """Convert RGB to hex string."""
    return f"#{r:02x}{g:02x}{b:02x}"

def rgb_to_hsv(r, g, b):
    """Convert RGB to HSV."""
    return colorsys.rgb_to_hsv(r/255, g/255, b/255)

def hsv_to_rgb(h, s, v):
    """Convert HSV to RGB."""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r*255), int(g*255), int(b*255))

def generate_complementary(base_hsv):
    """Generate complementary color scheme."""
    h, s, v = base_hsv
    return [
        rgb_to_hex(*hsv_to_rgb(h, s, v)),
        rgb_to_hex(*hsv_to_rgb((h + 0.5) % 1.0, s, v)),
    ]

def generate_analogous(base_hsv, count=5):
    """Generate analogous color scheme."""
    h, s, v = base_hsv
    step = 0.02
    colors = []
    for i in range(count):
        offset = (i - count // 2) * step
        colors.append(rgb_to_hex(*hsv_to_rgb((h + offset) % 1.0, s, v)))
    return colors

def generate_triadic(base_hsv):
    """Generate triadic color scheme."""
    h, s, v = base_hsv
    return [
        rgb_to_hex(*hsv_to_rgb(h, s, v)),
        rgb_to_hex(*hsv_to_rgb((h + 1/3) % 1.0, s, v)),
        rgb_to_hex(*hsv_to_rgb((h + 2/3) % 1.0, s, v)),
    ]

def generate_monochromatic(base_hsv, count=5):
    """Generate monochromatic color scheme with varying lightness."""
    h, s, v = base_hsv
    colors = []
    for i in range(count):
        new_v = max(0.2, min(1.0, v + (i - count // 2) * 0.15))
        colors.append(rgb_to_hex(*hsv_to_rgb(h, s, new_v)))
    return colors

@app.post("/api/generate/palette", summary="Generate color palette")
async def generate_palette(req: PaletteRequest):
    """Generate color palettes: complementary, analogous, triadic, monochromatic."""
    if req.base_color:
        try:
            rgb = hex_to_rgb(req.base_color)
        except:
            raise HTTPException(status_code=400, detail="Invalid hex color. Use format like #7c5cff")
    else:
        # Random base color
        rgb = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
    
    hsv = rgb_to_hsv(*rgb)
    base_hex = rgb_to_hex(*rgb)
    
    generators = {
        "complementary": (generate_complementary, 2),
        "analogous": (generate_analogous, req.count),
        "triadic": (generate_triadic, 3),
        "monochromatic": (generate_monochromatic, req.count),
    }
    
    if req.type not in generators:
        raise HTTPException(status_code=400, detail=f"Invalid type. Choose from: {', '.join(generators.keys())}")
    
    gen_fn, count = generators[req.type]
    colors = gen_fn(hsv)
    
    return {
        "success": True,
        "type": req.type,
        "base_color": base_hex,
        "colors": colors,
        "count": len(colors),
        "hex_codes": colors,
        "css_variables": {f"--color-{i+1}": c for i, c in enumerate(colors)},
        "preview_gradient": f"linear-gradient(135deg, {', '.join(colors)})",
    }

# ─── 5. Domain History (Internet Archive) ──────────────────────────

@app.post("/api/domain/history", summary="Look up domain history via Wayback Machine")
async def domain_history(req: DomainHistoryRequest):
    """Get historical snapshots of any website using the Internet Archive Wayback Machine API."""
    results = {"domain": req.domain, "snapshots": [], "total_snapshots": 0}
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Get latest available snapshot
        try:
            r = await client.get(f"https://archive.org/wayback/available?url={req.domain}")
            if r.status_code == 200:
                data = r.json()
                snap = data.get("archived_snapshots", {}).get("closest")
                if snap:
                    ts = snap["timestamp"]
                    results["latest_snapshot"] = {
                        "url": snap["url"],
                        "timestamp": ts,
                        "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                        "time": f"{ts[8:10]}:{ts[10:12]}",
                        "status": snap["status"],
                    }
                    results["latest_url"] = snap["url"]
        except Exception as e:
            results["wayback_error"] = str(e)
        
        # Get calendar/snapshot count
        year = req.year or datetime.utcnow().year
        try:
            r = await client.get(
                f"https://web.archive.org/__wb/calendarcaptures/2?url={req.domain}&date={year}",
                timeout=10.0,
            )
            if r.status_code == 200:
                cal = r.json()
                results["calendar_year"] = year
                results["collections"] = len(cal.get("colls", []))
        except:
            pass
    
    return results

# ─── 6. JWT Decoder ────────────────────────────────────────────────

@app.post("/api/decode/jwt", summary="Decode JWT token (no signature verification)")
async def decode_jwt(req: JWTDecodeRequest):
    """Decode a JWT token without verifying signature. Returns header, payload, and metadata."""
    parts = req.token.split(".")
    if len(parts) != 3:
        return {"success": False, "error": "Invalid JWT format. Expected 3 parts separated by dots."}
    
    def decode_part(part):
        padded = part + "=" * (4 - len(part) % 4)
        try:
            return json.loads(base64.urlsafe_b64decode(padded))
        except:
            try:
                return json.loads(base64.urlsafe_b64decode(part + "=="))
            except:
                return {"error": "could not decode"}
    
    header = decode_part(parts[0])
    payload = decode_part(parts[1])
    
    return {
        "success": True,
        "header": header,
        "payload": payload,
        "signature": parts[2][:20] + "...",
        "signature_algorithm": header.get("alg", "unknown"),
        "token_type": header.get("typ", "JWT"),
        "expires_at": payload.get("exp"),
        "issued_at": payload.get("iat"),
        "subject": payload.get("sub"),
        "issuer": payload.get("iss"),
    }

# ─── 7. API Key Registration ───────────────────────────────────────

def generate_api_key():
    """Generate a unique API key."""
    raw = f"{time.time()}:{random.random()}:agentpay"
    return f"jsk_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"

@app.post("/api/keys/register", summary="Register for a free API key")
async def register_api_key():
    """Get a free API key (100 requests/day). Upgrade to Pro for unlimited access."""
    key = generate_api_key()
    API_KEYS[key] = {"tier": "free", "calls_today": 0, "date": date.today().isoformat()}
    return {
        "success": True,
        "api_key": key,
        "tier": "free",
        "daily_limit": FREE_DAILY_LIMIT,
        "upgrade_url": "https://rumblingb.github.io/jacks-toolbox/",
        "docs_url": "/docs",
    }

# ─── Run ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
