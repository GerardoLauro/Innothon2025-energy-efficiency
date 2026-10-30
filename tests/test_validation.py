from energy_planner.core.validation import Activity, ValidationInput, Severity, validate


def test_validation_reports_cyclic_precedences():
    activities = [Activity("A", 15, 0, 60, 1, None, ["B"]),
                  Activity("B", 15, 0, 60, 1, None, ["A"])]
    result = validate(ValidationInput(activities, [2]*12, [0.25]*12, "min_cost", {}))
    assert any(issue.severity == Severity.ERROR for issue in result.issues)
