from energy_planner.core.tariffs import OfferType, classify_offer, infer_objective


def test_offer_classification_and_objective():
    assert classify_offer("PLACET variabile PUN") == OfferType.PLACET_VARIABILE
    assert infer_objective(OfferType.PLACET_VARIABILE) == "min_cost"
    assert infer_objective(OfferType.PLACET_FISSA) == "min_peak"
