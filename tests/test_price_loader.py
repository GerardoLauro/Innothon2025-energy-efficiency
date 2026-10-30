import pytest
from energy_planner.price.loader import PriceUnavailableError, load_city_hourly, parse_user_hourly_series


def test_price_list_parsing_and_missing_file():
    assert parse_user_hourly_series(",".join(["0.25"] * 24)) == [0.25] * 24
    with pytest.raises(PriceUnavailableError):
        load_city_hourly("Milano")


@pytest.mark.parametrize("text", [";".join(["0,25"]*24), " ".join(["0.25"]*24),
                                  "[" + ",".join(["0.25"]*24) + "]",
                                  "\n".join(f"{hour:02d}:00 0,25" for hour in range(24))])
def test_supported_price_formats(text):
    assert parse_user_hourly_series(text) == [0.25]*24


@pytest.mark.parametrize("text", ["0.25", ",".join(["0.25"]*23), "["+",".join(["NaN"]*24)+"]"])
def test_incomplete_or_nonfinite_prices_rejected(text):
    with pytest.raises(ValueError):
        parse_user_hourly_series(text)
