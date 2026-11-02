"""
Tool hub: universal tool discovery, orchestration support, generated internal tools, diagnostics and metrics.

Modules
  risk         six risk classes and what each may do without approval
  schema       a small JSON-schema validator (the subset tool schemas use)
  diagnostics  error categories and the recovery policy (what may be retried, how often)
  metrics      execution records and per-tool performance figures
  mcp_sync     MCP discovery → registry (added / removed / changed tools, snapshots)
  sandbox      static checks + isolated subprocess runner for generated code
  builder      Tool Builder: capability assessment, generation, validation, registration, versions
  charts       visualization specs built only from verified data
  registry     the unified view of every tool a company and a role can use
"""
