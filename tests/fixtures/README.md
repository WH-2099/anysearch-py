# Recorded AnySearch responses

`responses.json` contains responses captured from `https://api.anysearch.com` on 2026-10-28 using the REST endpoints and MCP `tools/call`.
`mcp_tools.json` contains the corresponding MCP `tools/list` discovery result and its JSON Schemas.
Each response records the operation, authentication mode, HTTP status, selected response headers, and body.

The samples cover search in JSON and Markdown, extraction, domain discovery, batch search, scoring, invalid credentials, invalid arguments, and an unknown MCP tool.
Credentials were redacted; request IDs were retained to verify error metadata.
The local MCP transport tests substitute the JSON-RPC ID so it matches each outgoing request.
Extraction content includes redacted example API keys from the public README.

These files are historical observations, not an authoritative API specification.
The unknown REST domain sample returned HTTP 502 with `Capabilities temporarily unavailable.`
The invalid-key samples returned HTTP 401 in REST and HTTP 200 with `isError: true` in MCP.
The batch sample contains one request ID for each query, and the score sample acknowledges queuing without proving persistence.

To refresh the samples, call the same public endpoints with explicit authorization, retain only response metadata and bodies, redact credentials, and review the diff before committing.
Do not record request authorization headers or copy `.env` into fixtures.
Run the default test suite after refreshing, then use `--live=all` to compare current service behavior.
