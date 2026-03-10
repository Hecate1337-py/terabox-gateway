"""TeraBox API client module.

This module handles all interactions with the TeraBox API,
including fetching file information, download links, and formatting responses.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse

import aiohttp

from config import headers, load_cookies
from utils import find_between, extract_thumbnail_dimensions, get_formatted_size


async def fetch_download_link(
    url: str, password: str = ""
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch file information from TeraBox share link using unified proxy API."""
    try:
        from config import PROXY_BASE_URL, PROXY_MODE_RESOLVE

        # Pass URL so load_cookies picks the right domain cookies
        cookies = load_cookies(url)

        # Extract surl from URL
        parsed_url = urlparse(url)
        if "surl=" in parsed_url.query:
            surl = parse_qs(parsed_url.query)["surl"][0]
        elif "/s/" in parsed_url.path:
            surl = parsed_url.path.split("/s/")[1].split("/")[0].split("?")[0]
        else:
            logging.error("Could not extract surl from URL")
            return {"error": "Invalid URL format", "errno": -1}

        # Remove leading "1" if present (TeraBox shortcode format)
        if surl.startswith("1"):
            surl = surl[1:]

        async with aiohttp.ClientSession(cookies=cookies, headers=headers) as session:
            params = {
                "mode": PROXY_MODE_RESOLVE,
                "surl": surl,
                "raw": "1",
            }
            if password:
                params["pwd"] = password

            logging.info(f"Fetching file list from unified proxy (mode=resolve): {PROXY_BASE_URL}")

            async with session.get(PROXY_BASE_URL, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logging.error(f"Proxy returned {response.status}: {error_text}")
                    return {
                        "error": f"Proxy error: {response.status}",
                        "errno": -1,
                        "details": error_text[:200],
                    }

                response_data = await response.json()

                if "error" in response_data:
                    error_msg = response_data.get("error", "Unknown error")
                    logging.error(f"Proxy error: {error_msg}")
                    if "jsToken" in error_msg or "cookie" in error_msg.lower():
                        return {
                            "error": error_msg,
                            "errno": -1,
                            "message": "Failed to extract authentication tokens. Cookies may be required.",
                        }
                    return {"error": error_msg, "errno": -1}

                if "upstream" in response_data:
                    api_response = response_data["upstream"]
                    logging.info(f"Proxy response source: {response_data.get('source', 'unknown')}")
                else:
                    api_response = response_data.get("data", response_data)

                errno = api_response.get("errno", -1)
                logging.info(f"Response errno: {errno}")

                if errno == 400141:
                    logging.warning("Link requires verification")
                    return {
                        "error": "Verification required",
                        "errno": 400141,
                        "message": "This link requires password or captcha verification",
                        "surl": surl,
                        "requires_password": True,
                    }

                if errno != 0:
                    error_msg = api_response.get("errmsg", "Unknown error")
                    logging.error(f"API error {errno}: {error_msg}")
                    return {"error": error_msg, "errno": errno}

                if "list" not in api_response:
                    logging.error(f"No file list in response. Keys: {list(api_response.keys())}")
                    return {"error": "No files found in response", "errno": -1}

                files = api_response["list"]
                logging.info(f"Found {len(files)} items")

                if files and files[0].get("isdir") == "1":
                    logging.info("Fetching directory contents")
                    js_token = api_response.get("jsToken")
                    log_id = api_response.get("dplogid")

                    if not js_token:
                        logging.warning("No jsToken for directory listing, returning folder info only")
                        return files

                    from config import PROXY_MODE_API
                    dir_params = {
                        "mode": PROXY_MODE_API,
                        "jsToken": js_token,
                        "shorturl": surl,
                        "dir": files[0]["path"],
                        "order": "asc",
                        "by": "name",
                    }
                    if log_id:
                        dir_params["dplogid"] = log_id
                    if password:
                        dir_params["pwd"] = password

                    async with session.get(PROXY_BASE_URL, params=dir_params) as dir_response:
                        if dir_response.status != 200:
                            logging.warning("Failed to fetch directory contents, returning folder info")
                            return files

                        dir_data = await dir_response.json()
                        if "data" in dir_data:
                            dir_data = dir_data["data"]

                        if "list" in dir_data and dir_data.get("errno") == 0:
                            files = dir_data["list"]
                            logging.info(f"Found {len(files)} files in directory")
                        else:
                            logging.warning("Failed to parse directory contents, returning folder info")

                return files

    except aiohttp.ClientResponseError as e:
        logging.error(f"HTTP error: {e.status} - {e.message}")
        return {"error": f"HTTP error: {e.status}", "errno": -1}
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        return {"error": str(e), "errno": -1}


async def format_file_info(file_data: Dict[str, Any]) -> Dict[str, Any]:
    """Format file information for API response."""
    thumbnails = {}
    if "thumbs" in file_data:
        for key, url in file_data["thumbs"].items():
            if url:
                dimensions = extract_thumbnail_dimensions(url)
                thumbnails[dimensions] = url

    return {
        "filename": file_data.get("server_filename", "Unknown"),
        "size": await get_formatted_size(file_data.get("size", 0)),
        "size_bytes": file_data.get("size", 0),
        "download_link": file_data.get("dlink", ""),
        "is_directory": file_data.get("isdir") == "1",
        "thumbnails": thumbnails,
        "path": file_data.get("path", ""),
        "fs_id": file_data.get("fs_id", ""),
    }


async def fetch_direct_links(
    url: str, password: str = ""
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch files with direct download links."""
    try:
        files = await fetch_download_link(url, password)

        if isinstance(files, dict) and "error" in files:
            return files

        # Pass URL for domain-aware cookie selection
        session_cookies = load_cookies(url)

        async with aiohttp.ClientSession(
            cookies=session_cookies,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30, connect=10),
        ) as session:
            results = []
            for item in files or []:
                if not isinstance(item, dict):
                    logging.warning(f"Skipping non-dict item: {type(item)}")
                    continue

                dlink = item.get("dlink") or ""
                logging.info(f"Direct link: {dlink}")

                direct_link = None
                if dlink:
                    try:
                        async with session.head(dlink, allow_redirects=False) as response:
                            direct_link = response.headers.get("Location")
                    except Exception as e:
                        logging.error(f"Error getting direct link: {e}")

                results.append({
                    "filename": item.get("server_filename", "Unknown"),
                    "size": await get_formatted_size(item.get("size", 0)),
                    "size_bytes": item.get("size", 0),
                    "link": dlink,
                    "direct_link": direct_link,
                    "thumbnail": (item.get("thumbs") or {}).get("url3", ""),
                })

            return results

    except Exception as e:
        logging.error(f"Error in fetch_direct_links: {e}")
        return {"error": str(e), "errno": -1}


async def _gather_format_file_info(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run format_file_info concurrently for a list of file dicts."""
    tasks = [format_file_info(item) for item in files if isinstance(item, dict)]
    if not tasks:
        return []
    return await asyncio.gather(*tasks)


async def _normalize_api2_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize items from fetch_direct_links to /api response shape."""
    out: List[Dict[str, Any]] = []
    for item in items or []:
        try:
            if not isinstance(item, dict):
                continue
            filenamestr = item.get("filename") or item.get("server_filename", "Unknown")
            size_h = (
                item.get("size")
                if isinstance(item.get("size"), str)
                else await get_formatted_size(item.get("size", 0))
            )
            size_b = item.get("size_bytes", item.get("size", 0))
            download = (
                item.get("direct_link")
                or item.get("download_link")
                or item.get("link")
                or item.get("dlink")
                or ""
            )
            thumbs: Dict[str, str] = {}
            thumb_single = item.get("thumbnail") or (item.get("thumbs") or {}).get("url3")
            if thumb_single:
                thumbs["original"] = thumb_single
            formatted = {
                "filename": filenamestr,
                "size": size_h,
                "size_bytes": size_b,
                "download_link": download,
                "is_directory": item.get("is_directory", False),
                "thumbnails": thumbs,
                "path": item.get("path", ""),
                "fs_id": item.get("fs_id", ""),
            }
            if item.get("direct_link"):
                formatted["direct_link"] = item["direct_link"]
            out.append(formatted)
        except Exception:
            continue
    return out
