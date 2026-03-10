"""Configuration module for TeraBox API Gateway.

This module contains all configuration settings, constants, headers,
and cookie loading logic used throughout the application.

Multi-domain cookie support:
- COOKIE_JSON         : cookies untuk domain default (terabox.com / fallback)
- COOKIE_JSON_1024    : cookies untuk 1024terabox.com
- COOKIE_JSON_APP     : cookies untuk terabox.app
- COOKIE_JSON_SHARE   : cookies untuk teraboxshare.com

Semua variable di atas bisa diset di Vercel Environment Variables.
"""

import logging
import os
from typing import Dict
from urllib.parse import urlparse

# Logging configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Allowed TeraBox domains
ALLOWED_HOSTS: set[str] = {
    "terabox.app",
    "www.terabox.app",
    "teraboxshare.com",
    "www.teraboxshare.com",
    "terabox.com",
    "www.terabox.com",
    "1024terabox.com",
    "www.1024terabox.com",
    "1024tera.com",
    "www.1024tera.com",
}

# Unified Cloudflare Worker proxy configuration
PROXY_BASE_URL: str = "https://tbx-proxy.shakir-ansarii075.workers.dev/"
PROXY_MODE_RESOLVE: str = "resolve"
PROXY_MODE_PAGE: str = "page"
PROXY_MODE_API: str = "api"
PROXY_MODE_STREAM: str = "stream"
PROXY_MODE_SEGMENT: str = "segment"

# Default HTTP headers for requests
headers: Dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Mapping: domain keyword -> environment variable name
# Urutan prioritas dari paling spesifik ke paling umum
_DOMAIN_COOKIE_MAP = [
    ("1024terabox.com", "COOKIE_JSON_1024"),
    ("1024tera.com",    "COOKIE_JSON_1024"),  # alias domain yang sama
    ("terabox.app",     "COOKIE_JSON_APP"),
    ("teraboxshare.com","COOKIE_JSON_SHARE"),
    ("terabox.com",     "COOKIE_JSON"),       # default / fallback
]


def _parse_cookie_env(env_var: str) -> dict[str, str] | None:
    """Parse cookie JSON dari satu environment variable.

    Args:
        env_var: Nama environment variable yang akan dibaca

    Returns:
        dict cookie atau None jika tidak ada / gagal parse
    """
    raw = os.getenv(env_var)
    if not raw:
        return None
    try:
        import json
        data = json.loads(raw)
        if isinstance(data, dict):
            logging.info(f"Loaded cookies from env var: {env_var}")
            return {k: str(v) for k, v in data.items()}
    except Exception as e:
        logging.warning(f"Failed to parse {env_var}: {e}")
    return None


def load_cookies(url: str = "") -> dict[str, str]:
    """Load cookies yang sesuai dengan domain URL yang diminta.

    Jika URL diberikan, akan dicari cookies yang paling cocok
    untuk domain tersebut. Jika tidak ada yang cocok atau URL
    kosong, akan fallback ke COOKIE_JSON (default).

    Priority order per domain:
    1. COOKIE_JSON_1024  -> untuk 1024terabox.com / 1024tera.com
    2. COOKIE_JSON_APP   -> untuk terabox.app
    3. COOKIE_JSON_SHARE -> untuk teraboxshare.com
    4. COOKIE_JSON       -> default / fallback untuk semua domain

    Args:
        url: URL TeraBox yang sedang diproses (opsional)

    Returns:
        dict[str, str]: Dictionary cookie key-value pairs
    """
    # Tentukan domain dari URL jika diberikan
    target_domain = ""
    if url:
        try:
            target_domain = urlparse(url).netloc.lower()
        except Exception:
            pass

    # Cari cookies yang paling cocok untuk domain ini
    if target_domain:
        for domain_keyword, env_var in _DOMAIN_COOKIE_MAP:
            if domain_keyword in target_domain:
                cookies = _parse_cookie_env(env_var)
                if cookies:
                    logging.info(f"Using {env_var} for domain: {target_domain}")
                    return cookies
                # Kalau env var khusus domain ini tidak ada, lanjut ke berikutnya
                logging.debug(f"{env_var} not set, trying next option for {target_domain}")

    # Fallback: coba semua env var secara berurutan
    for _, env_var in _DOMAIN_COOKIE_MAP:
        cookies = _parse_cookie_env(env_var)
        if cookies:
            logging.info(f"Fallback: using {env_var}")
            return cookies

    # Legacy support: TERABOX_COOKIES_JSON
    cookies = _parse_cookie_env("TERABOX_COOKIES_JSON")
    if cookies:
        return cookies

    # Legacy support: TERABOX_COOKIES_FILE
    file_path = os.getenv("TERABOX_COOKIES_FILE")
    if file_path:
        try:
            import json
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                logging.info(f"Loaded cookies from file: {file_path}")
                return {k: str(v) for k, v in data.items()}
        except Exception as e:
            logging.warning(f"Failed to read cookie file: {e}")

    logging.warning("Cookies not loaded. API requests will likely fail.")
    return {}
