# DNS/Path Gateway

Version: 1.0.3.

The DNS/path gateway is the preferred public access pattern for Home UI, project UI/API routes, and project MCP endpoints.

`mcp-memory` does not run a DNS server and does not resolve names itself. DNS is configured outside the application so a name such as `mcp-memory.local` points to the machine running Home UI. Home UI then uses path prefixes to route traffic to the right project.

## Request Shape

Home UI listens on one host/port, by default:

```text
http://127.0.0.1:8764/
```

When DNS is configured, the same Home UI can be reached through a stable name:

```text
http://mcp-memory.local:8764/
```

Project gateway paths are:

```text
http://mcp-memory.local:8764/<project_id>/ui/
http://mcp-memory.local:8764/<project_id>/schema
http://mcp-memory.local:8764/<project_id>/records/...
http://mcp-memory.local:8764/<project_id>/mcp
```

The first path segment is always the project id. Home UI strips that segment, forwards the request to the project's local HTTP or MCP server, and rewrites generated HTML links back to gateway paths.

Direct project ports still exist for local/manual use:

```text
http://127.0.0.1:8765/ui/
http://127.0.0.1:8765/schema
http://127.0.0.1:9876/mcp
```

## Code Map

- `src/mcp_memory/gui/home.py`
  - `serve_ui_home(...)` binds Home UI to `--host`/`--port`.
  - `_project_gateway_route(...)` detects `/<project_id>/...` gateway requests.
  - `_proxy_to_project(...)` forwards HTTP/API requests to `project.http_host:project.http_port` and MCP requests to `project.mcp_host:project.mcp_port`.
  - `normalize_base_url(...)`, `set_app_base_url(...)`, and `public_base_url(...)` validate and store the public root URL used in generated links.
  - `rewrite_gateway_html(...)` rewrites project UI links such as `/ui/...` to `/<project_id>/ui/...`.
  - `rewrite_gateway_location(...)` rewrites redirect `Location` headers back through the gateway.
- `src/mcp_memory/runtime.py`
  - `ProjectRuntimeManager` starts/stops project HTTP and MCP processes from Home UI.
  - `get_project_runtime(...)` checks `/health` on both project services before gateway requests are proxied.
- `src/mcp_memory/services/projects.py`
  - `validate_project_id(...)` rejects project ids that would collide with Home UI root paths such as `assets`, `projects`, `setup`, `settings`, `health`, `mcp`, and `ui`.
- `src/mcp_memory/config/models.py`
  - `AppConfig.base_url` stores the optional public Base URL.
  - `ProjectConfig.http_host`, `http_port`, `mcp_host`, and `mcp_port` store the local targets that Home UI proxies to.

## Base URL

Base URL is the public root URL shown in Home UI links and generated MCP config. It does not configure DNS by itself.

Valid examples:

```text
http://mcp-memory.local:8764
http://mcp-memory.lan:8764
https://mcp-memory.example.test
```

Invalid examples:

```text
http://mcp-memory.local:8764/sample
http://mcp-memory.local:8764/?x=1
mcp-memory.local:8764
```

Base URL must be an `http` or `https` root URL with no path, query, or fragment. A trailing slash is accepted and removed.

If Base URL is blank, Home UI builds public links from the incoming `Host` header. This is convenient for local use, but a configured Base URL is better when using DNS, reverse proxies, or MCP clients.

## Same-Machine Setup

Use this when browser and MCP client run on the same Windows machine as Home UI.

1. Add a hosts entry in `C:\Windows\System32\drivers\etc\hosts`:

```text
127.0.0.1 mcp-memory.local
```

2. Start Home UI:

```powershell
mcp-memory run-ui-home
```

3. Open:

```text
http://mcp-memory.local:8764/
```

4. In Home UI, set Base URL:

```text
http://mcp-memory.local:8764
```

5. Start the project from Home UI, or start both project services manually:

```powershell
mcp-memory run-http-api sample
mcp-memory run-mcp sample
```

## LAN Setup

Use this when other machines on the local network need to reach Home UI.

1. Pick a stable LAN IP for the machine running Home UI, for example:

```text
192.168.1.50
```

2. Configure local DNS or each client hosts file:

```text
192.168.1.50 mcp-memory.local
```

3. Start Home UI on a network interface, not only loopback:

```powershell
mcp-memory run-ui-home --host 0.0.0.0 --port 8764
```

4. Allow inbound TCP `8764` in Windows Firewall.

5. Open from another machine:

```text
http://mcp-memory.local:8764/
```

6. Set Base URL in Home UI:

```text
http://mcp-memory.local:8764
```

Project HTTP and MCP services may remain bound to `127.0.0.1` if they are started by Home UI on the same machine. External clients only need to reach Home UI port `8764`; Home UI then proxies to the local project ports.

## Reverse Proxy Setup

A reverse proxy is optional. It is useful when you want port `80`, port `443`, TLS, or a cleaner URL without `:8764`.

Recommended shape:

```text
https://mcp-memory.example.test/ -> http://127.0.0.1:8764/
```

Then set Base URL to:

```text
https://mcp-memory.example.test
```

Keep the gateway mounted at the domain root. Path-prefix deployments such as `https://example.test/memory` are not supported by Base URL validation, because Base URL intentionally rejects paths.

If the reverse proxy changes request bodies or strips headers, MCP clients may fail. Preserve method, path, query string, body, `Content-Type`, and `Accept` headers.

## MCP Client URL

Use the gateway MCP endpoint in agent/client config:

```text
http://mcp-memory.local:8764/<project_id>/mcp
```

For example:

```json
{
  "mcpServers": {
    "mcp-memory-sample": {
      "url": "http://mcp-memory.local:8764/sample/mcp"
    }
  }
}
```

## Troubleshooting

### Name Does Not Resolve

Symptoms:

- Browser says the host cannot be found.
- `ping mcp-memory.local` cannot find an address.

Checks:

- Confirm the hosts file or DNS record points to the Home UI machine.
- On Windows, edit `C:\Windows\System32\drivers\etc\hosts` as Administrator.
- Flush DNS cache if needed:

```powershell
ipconfig /flushdns
```

### Browser Cannot Connect

Symptoms:

- Name resolves, but the browser cannot connect.
- Connection is refused or times out.

Checks:

- Home UI must be running.
- Same-machine default:

```powershell
mcp-memory run-ui-home
```

- LAN access:

```powershell
mcp-memory run-ui-home --host 0.0.0.0 --port 8764
```

- Confirm firewall allows inbound TCP `8764`.
- Confirm no other process already owns the port.

### Gateway Links Still Use 127.0.0.1

Symptoms:

- Home UI opens through DNS, but project links or MCP config show `127.0.0.1`.

Checks:

- Set Base URL in Home UI to the public root:

```text
http://mcp-memory.local:8764
```

- Do not include `/<project_id>` or `/ui/` in Base URL.

### Base URL Save Fails

Symptoms:

- Home UI redirects with a failure flash after saving Base URL.

Checks:

- Include `http://` or `https://`.
- Use only the root URL.
- Remove paths, query strings, and fragments.

### Project Gateway Says Project Unavailable

Symptoms:

- `/<project_id>/ui/` returns a project unavailable page.
- API/MCP gateway calls return `project_unavailable`.

Checks:

- Start the project from Home UI.
- If starting manually, both project services must be running:

```powershell
mcp-memory run-http-api <project_id>
mcp-memory run-mcp <project_id>
```

- Check direct health endpoints:

```text
http://127.0.0.1:8765/health
http://127.0.0.1:9876/health
```

Home gateway currently requires both HTTP and MCP services to be healthy before proxying any project path.

### Gateway Route Returns Project Not Found

Symptoms:

- `/<project_id>/...` returns `Project Not Found`.

Checks:

- Confirm the project id in the URL exactly matches the registered project id.
- Project ids are path-sensitive. `sample_project` and `sample-project` are different ids.
- Reserved root ids cannot be used as project ids: `assets`, `projects`, `setup`, `settings`, `health`, `mcp`, and `ui`.

### MCP Client Fails Through Gateway

Symptoms:

- Browser UI works, but MCP client cannot initialize.

Checks:

- Use `/<project_id>/mcp`, not direct Home UI `/mcp`.
- Ensure the project MCP service is running.
- Preserve `Content-Type` and `Accept` headers if using a reverse proxy.
- Confirm the client can reach the same URL outside the application.

### .local Behaves Inconsistently

Symptoms:

- Some clients resolve `mcp-memory.local`, others do not.

Cause:

- `.local` is often used by mDNS/Bonjour and may not behave like normal unicast DNS on every network.

Options:

- Keep `.local` if it works in your environment.
- Prefer a local DNS zone such as `.lan`.
- Use `home.arpa` for home networks, for example `mcp-memory.home.arpa`.

### HTTPS Is Needed

Home UI serves plain HTTP. Use a reverse proxy for HTTPS/TLS and set Base URL to the HTTPS root URL. Do not expose an unauthenticated local knowledge base to untrusted networks.

## Security Notes

The default bind address is `127.0.0.1`, which keeps Home UI local to the machine. Binding to `0.0.0.0` makes Home UI reachable from the network if the firewall allows it.

This project is designed for local/offline use. Treat DNS/LAN exposure as trusted-network exposure unless authentication and TLS are provided by a separate fronting layer.

## Verification Commands

From the Home UI machine:

```powershell
Resolve-DnsName mcp-memory.local
Invoke-WebRequest http://mcp-memory.local:8764/health
Invoke-WebRequest http://mcp-memory.local:8764/<project_id>/schema
```

From another LAN machine:

```powershell
Resolve-DnsName mcp-memory.local
Invoke-WebRequest http://mcp-memory.local:8764/health
```

If DNS is not ready yet, test the same Home UI by IP:

```powershell
Invoke-WebRequest http://192.168.1.50:8764/health
```
