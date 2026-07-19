# Changelog

## Unreleased

- Dropped armv7 from the add-on's multi-arch builds: `sharp` (pulled in
  transitively by upstream `revolut-x-api`) has no prebuilt binary for
  linuxmusl-armv7 and fails to compile from source there either.
- Added the HACS custom_component (`custom_components/revolutx_mcp`) as a second,
  in-process install method — see its own README.

## 1.0.0

- Initial release
- Market data, account balances, and strategy backtesting via the Revolut X MCP server
- Network MCP transport (HTTP `/rpc`, `/health`) for Claude Desktop custom connectors
- Multi-arch builds: aarch64, amd64, armv7
