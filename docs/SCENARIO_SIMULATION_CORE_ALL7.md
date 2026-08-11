# Scenario Simulation Core — All 7 Locked Scenarios

This patch completes the deterministic calculation core only. It does not edit
`app.py`, `hr_agent.py`, existing Attrition/Replacement/Headcount/Performance
modules, or frontend code.

## Locked scenarios
1. Employee Promotion
2. Employee Transfer
3. Headcount Reduction
4. Workforce Expansion / Hiring
5. Budget Change
6. Skill Gap / Reskilling
7. Business Demand / Workload Change

## Design rule
- Current state comes from existing `Data/*.csv`.
- Simulation-only features/assumptions come from `Data/Simulation/*.csv`.
- Engines calculate hypothetical before/after state in memory.
- No source CSV is mutated.
- No LLM performs arithmetic.
- A single `SimulationService` routes all seven scenarios.

## Two future interfaces
Both will reuse the same `SimulationService`:

1. Dedicated Scenario Simulator UI -> REST simulation router -> SimulationService.
2. Existing HR chatbot -> ScenarioSimulationTool -> SimulationService.

This patch intentionally does not connect either interface yet. That is the
next integration batch after deterministic engines are validated.
