"""OpenAPI 3.0 spec for the FluxGate API."""
from .api import VERSION

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "FluxGate API",
        "version": VERSION,
        "description": "Self-hosted proxy management panel API. "
                       "Backend endpoints use X-API-Token; user/admin endpoints use session cookies.",
    },
    "paths": {
        "/api/health": {
            "get": {
                "summary": "Liveness probe",
                "responses": {"200": {"description": "status + version + db"}},
            }
        },
        "/api/metrics": {
            "get": {
                "summary": "Prometheus metrics",
                "responses": {"200": {"description": "text/plain metrics"}},
            }
        },
        "/api/subscribe": {
            "get": {
                "summary": "Subscription links",
                "parameters": [
                    {"name": "token", "in": "query", "schema": {"type": "string"}},
                    {"name": "api_key", "in": "query", "schema": {"type": "string"}},
                    {"name": "sub_type", "in": "query",
                     "schema": {"type": "string", "enum": ["ss", "v2ray", "trojan", "clash"]}},
                ],
                "responses": {"200": {"description": "subscription text"}, "404": {"description": "not found"}},
            }
        },
        "/api/subscribe/qr": {
            "get": {
                "summary": "QR code PNG of subscription URL",
                "parameters": [
                    {"name": "token", "in": "query", "schema": {"type": "string"}},
                    {"name": "sub_type", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "image/png"}},
            }
        },
        "/api/proxy_configs/{node_id}": {
            "get": {
                "summary": "Node config (backend)",
                "parameters": [{"name": "node_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "security": [{"ApiToken": []}],
                "responses": {"200": {"description": "node config"}, "401": {"description": "unauthorized"}},
            },
            "post": {
                "summary": "Traffic report + heartbeat (backend)",
                "parameters": [{"name": "node_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "security": [{"ApiToken": []}],
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"200": {"description": "ok"}},
            },
        },
        "/api/checkin": {
            "post": {
                "summary": "Daily check-in reward",
                "security": [{"Session": []}],
                "responses": {"200": {"description": "reward"}, "401": {"description": "login required"}},
            }
        },
        "/api/orders": {
            "post": {
                "summary": "Create order",
                "security": [{"Session": []}],
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"200": {"description": "order"}, "401": {"description": "login required"}},
            }
        },
        "/api/system_status": {
            "get": {
                "summary": "Admin stats",
                "security": [{"Session": []}],
                "responses": {"200": {"description": "stats"}, "403": {"description": "admin required"}},
            }
        },
    },
    "components": {
        "securitySchemes": {
            "ApiToken": {"type": "apiKey", "in": "header", "name": "X-API-Token"},
            "Session": {"type": "apiKey", "in": "cookie", "name": "session"},
        }
    },
}
