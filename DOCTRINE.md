# AiGNITE Doctrine

## The seven standards
1. Fix root causes, never symptoms.
2. Smoke test hits real business endpoints with a real token and asserts non-empty schema-valid data.
3. No silent mock or fallback data outside development. Fail loud.
4. After every migration, assert the expected table count.
5. Before any fix: curl endpoints, query the database, read the logs, document actual versus reported.
6. Maintain contracts.md: every frontend call mapped to its backend endpoint.
7. Learn from GoviHub.

## The GoviHub post-mortem
GoviHub lost five days. Ten database tables silently failed to create. The frontend fell back to
mock data that masked the failure. Three fix cycles patched display symptoms while the backend was
broken at the root. A five-minute curl audit of the real endpoints would have caught it on day one.
Every rule above exists to make that failure impossible here.
