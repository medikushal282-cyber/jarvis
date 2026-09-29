import ipaddress
import socket
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Dict, Any, Optional, Tuple, Set

from app.tools.base import Tool, ToolResult, ToolContext

DEFAULT_MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB


def is_private_or_internal_ip(ip_str: str) -> bool:
    """
    Evaluates whether an IP address is in a private, loopback, link-local,
    multicast, or cloud-metadata range.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check IPv4-mapped IPv6 (e.g., ::ffff:127.0.0.1)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True

        # Explicit check for cloud metadata service
        if str(ip) == "169.254.169.254":
            return True

        return False
    except ValueError:
        return True


def validate_url_for_ssrf(url: str, allow_private: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validates a URL against SSRF and private-network access rules.
    Returns (is_valid, error_message).
    """
    if not url:
        return False, "URL is required"

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    if parsed.scheme not in ["http", "https"]:
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing hostname"

    # Quick check for obvious localhost/private hostnames
    lower_host = hostname.lower()
    if lower_host in ["localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"]:
        if not allow_private:
            return False, f"Access to private/loopback destination '{hostname}' is blocked by security policy."

    if not allow_private:
        try:
            # Resolve DNS to all IP addresses
            addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            resolved_ips: Set[str] = {item[4][0] for item in addr_info}
            for ip in resolved_ips:
                if is_private_or_internal_ip(ip):
                    return False, f"Access to private/internal IP address '{ip}' (resolved from '{hostname}') is blocked by SSRF security policy."
        except socket.gaierror as e:
            return False, f"Failed to resolve hostname '{hostname}': {e}"
        except Exception as e:
            return False, f"Security check failed for hostname '{hostname}': {e}"

    return True, None


def execute_http_request_streamed(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Any] = None,
    max_bytes: int = DEFAULT_MAX_RESPONSE_SIZE,
    timeout: int = 15,
    allow_private: bool = False
) -> Dict[str, Any]:
    """
    Executes an HTTP request with SSRF protection and strict streaming memory limits.
    """
    valid, err_msg = validate_url_for_ssrf(url, allow_private=allow_private)
    if not valid:
        return {
            "success": False,
            "error": {"code": "SSRF_BLOCKED", "message": err_msg}
        }

    req_headers = {"User-Agent": "JARVIS-Agent/1.0"}
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body_bytes = json.dumps(data).encode("utf-8")
            if "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/json"
        elif isinstance(data, str):
            body_bytes = data.encode("utf-8")
        elif isinstance(data, bytes):
            body_bytes = data

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            resp_headers = dict(response.headers)
            
            # Incremental chunked reading to strictly enforce memory limits
            chunks = []
            total_read = 0
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > max_bytes:
                    return {
                        "success": False,
                        "error": {
                            "code": "RESPONSE_SIZE_EXCEEDED",
                            "message": f"HTTP response exceeded maximum allowed limit of {max_bytes} bytes (read {total_read} bytes so far)."
                        }
                    }
                chunks.append(chunk)

            raw_body = b"".join(chunks)
            charset = response.headers.get_content_charset() or "utf-8"
            body_text = raw_body.decode(charset, errors="replace")

            # Try JSON parsing if applicable
            parsed_json = None
            if "application/json" in resp_headers.get("Content-Type", ""):
                try:
                    parsed_json = json.loads(body_text)
                except Exception:
                    pass

            return {
                "success": True,
                "status_code": status_code,
                "headers": resp_headers,
                "body": parsed_json if parsed_json is not None else body_text,
                "bytes_read": len(raw_body)
            }
    except urllib.error.HTTPError as e:
        raw_error_body = e.read(8192)  # Read small snippet for diagnostics
        return {
            "success": False,
            "status_code": e.code,
            "error": {
                "code": f"HTTP_{e.code}",
                "message": f"HTTP Error {e.code}: {e.reason}",
                "details": raw_error_body.decode("utf-8", errors="replace")[:500]
            }
        }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "error": {"code": "CONNECTION_ERROR", "message": f"URL Error: {e.reason}"}
        }
    except Exception as e:
        return {
            "success": False,
            "error": {"code": "HTTP_EXECUTION_ERROR", "message": str(e)}
        }


class HttpGetTool(Tool):
    name = "http_get"
    description = "Performs an HTTP GET request to an external URL with SSRF protection."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target HTTP/HTTPS URL"},
            "headers": {"type": "object", "description": "Optional HTTP headers"},
            "max_response_size": {"type": "integer", "description": "Max bytes to read (default 5MB)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 15)"}
        },
        "required": ["url"]
    }
    required_permissions = ["http.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
        headers = arguments.get("headers")
        max_bytes = int(arguments.get("max_response_size", DEFAULT_MAX_RESPONSE_SIZE))
        timeout = int(arguments.get("timeout", 15))
        
        # Security: trusted policy controls allow_private, NOT tool arguments!
        allow_private = context.allow_private_http if context else False

        res = execute_http_request_streamed(
            method="GET",
            url=url,
            headers=headers,
            max_bytes=max_bytes,
            timeout=timeout,
            allow_private=allow_private
        )
        if not res.get("success"):
            return ToolResult(
                success=False,
                tool=self.name,
                error=res.get("error")
            )
        return ToolResult(
            success=True,
            tool=self.name,
            result=res
        )


class HttpPostTool(Tool):
    name = "http_post"
    description = "Performs an HTTP POST request to an external URL."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "data": {"type": "object", "description": "Payload (JSON object or string)"},
            "headers": {"type": "object", "description": "Optional HTTP headers"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 15)"}
        },
        "required": ["url"]
    }
    required_permissions = ["http.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
        data = arguments.get("data")
        headers = arguments.get("headers")
        timeout = int(arguments.get("timeout", 15))
        allow_private = context.allow_private_http if context else False

        res = execute_http_request_streamed(
            method="POST",
            url=url,
            headers=headers,
            data=data,
            timeout=timeout,
            allow_private=allow_private
        )
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error=res.get("error"))
        return ToolResult(success=True, tool=self.name, result=res)


class HttpPutTool(Tool):
    name = "http_put"
    description = "Performs an HTTP PUT request."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "data": {"type": "object", "description": "Payload"},
            "headers": {"type": "object", "description": "Optional HTTP headers"}
        },
        "required": ["url"]
    }
    required_permissions = ["http.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
        data = arguments.get("data")
        headers = arguments.get("headers")
        allow_private = context.allow_private_http if context else False

        res = execute_http_request_streamed(method="PUT", url=url, headers=headers, data=data, allow_private=allow_private)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error=res.get("error"))
        return ToolResult(success=True, tool=self.name, result=res)


class HttpPatchTool(Tool):
    name = "http_patch"
    description = "Performs an HTTP PATCH request."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "data": {"type": "object", "description": "Payload"},
            "headers": {"type": "object", "description": "Optional HTTP headers"}
        },
        "required": ["url"]
    }
    required_permissions = ["http.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
        data = arguments.get("data")
        headers = arguments.get("headers")
        allow_private = context.allow_private_http if context else False

        res = execute_http_request_streamed(method="PATCH", url=url, headers=headers, data=data, allow_private=allow_private)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error=res.get("error"))
        return ToolResult(success=True, tool=self.name, result=res)


class HttpDeleteTool(Tool):
    name = "http_delete"
    description = "Performs an HTTP DELETE request."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "headers": {"type": "object", "description": "Optional HTTP headers"}
        },
        "required": ["url"]
    }
    required_permissions = ["http.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
        headers = arguments.get("headers")
        allow_private = context.allow_private_http if context else False

        res = execute_http_request_streamed(method="DELETE", url=url, headers=headers, allow_private=allow_private)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error=res.get("error"))
        return ToolResult(success=True, tool=self.name, result=res)
