from energy_planner.core.compiler import compile_instance
from energy_planner.core.triple_store import Triple, TripleStore


def test_compiler_produces_consistent_slot_vectors():
    store = TripleStore()
    store.ingest([Triple("horizon", "hours", 1), Triple("price", "per_hour", [0.25]),
                  Triple("activity:demo", "duration_min", 15)])
    instance = compile_instance(store)
    assert instance["time"] == {"slot_minutes": 5, "slots": 12}
    assert len(instance["pricing"]) == len(instance["workforce"]) == 12
    assert instance["activities"][0]["duration_slots"] == 3
