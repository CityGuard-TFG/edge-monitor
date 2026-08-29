# Edge Monitor Repository Guidance

Local status dashboard for a CityGuard Pi edge node: system health, camera
preview, Hailo-8L detection, and GPS quality/coordinates. It is a bring-up and
field-debugging tool, not part of the anonymization/capture/upload pipeline —
it must never persist or forward raw frames, and it carries no auth by design
(LAN-only, read-only status). Read `03-hardware-deployment.md` and
`01-architecture.md` in the canonical knowledge base before changing what it
reports. Commits reference `CityGuard-TFG/edge-monitor#<issue>`.
