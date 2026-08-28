.PHONY: incident demo demo-notion

incident:
	@./scripts/run_incident.sh

demo:
	@./scripts/demo.sh

demo-notion:
	@./scripts/demo.sh --mock-agent
