# Spec Delta

## ADDED Requirements

### Requirement: Elyra canvas keyboard navigation and ARIA landmarks
The Elyra canvas container SHALL provide accessible ARIA region landmarks, support Tab and arrow key traversal across placed nodes and ports, and emit screen-reader announcements when nodes are selected or links are established.

#### Scenario: Canvas viewport marked with application landmark
- **WHEN** the canvas component mounts
- **THEN** the canvas wrapper element has `role="region"` and an appropriate `aria-label` identifying the interactive pipeline editor

#### Scenario: Tab key navigates between canvas nodes
- **WHEN** the user presses Tab within the canvas viewport
- **THEN** keyboard focus cycles sequentially through placed canvas nodes and their input/output ports
