# MCP server connections (Phase K, part 3)

Admins connect a Model Context Protocol server (HTTP JSON-RPC at `<server_url>/mcp`), review the tools it exposes, and grant them to AI employee roles one tool at a time.

## Flow
1. `POST /integration-manager/integrations` (`provider_type: "mcp"`, credentials `server_url`, optional `api_key`, `auth_header_name`) -> validated and stored encrypted.
2. `POST .../test`, then `PATCH ... {is_enabled: true}`.
3. `POST .../discover` -> each tool with EAAWP's risk level (`low|medium|high`) and the server's description (untrusted text).
4. Grants: `call_tool` plus `mcp_tool:<tool name>` per role. **Both are required**; granting `call_tool` alone exposes nothing.
5. `POST .../execute` (or an AI employee through the dynamic tool) -> permission check -> provider call.

## Safety rules (all tested against a real local MCP server)
- Server address: https/http only; link-local/metadata addresses always blocked; loopback/private blocked unless `ALLOW_PRIVATE_MCP_HOSTS=true` (dev/test only). Re-checked on every request, not only when saved.
- Redirects are never followed (a redirect would send the request, and its API key, elsewhere).
- An API key is only sent to https servers; the auth header name must be a plain token and not Host/Cookie/Content-*.
- Risk is judged on every word of the tool name, so `get_user_and_delete_account` is high risk. High-risk tools never run, even if granted.
- Tools with prompt-injection patterns in name/description are dropped; credentials cannot be passed as tool arguments; responses are size-capped and treated as data.
- Changing a connection to a different server URL deletes its per-tool grants (they were reviewed for another server).
- Members listing integrations see only scheme and host (a path can contain a secret).

## Not verified / known limits
- A DNS answer can change between the address check and the connection (DNS rebinding); addresses are re-checked per call but not pinned.
- Tested against a minimal HTTP JSON-RPC server, not against third-party MCP servers, OAuth-based or SSE/streaming transports.
- Only plain-text tool results are returned.
