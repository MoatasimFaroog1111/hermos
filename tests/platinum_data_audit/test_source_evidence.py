import pytest

from scripts.platinum_data_audit.source_evidence import yahoo_metadata, cme_metadata


def test_yahoo_metadata_is_not_a_verified_roll_or_completion_contract():
    payload = {"chart": {"result": [{"meta": {"symbol": "PL=F", "currency": "USD",
               "instrumentType": "FUTURE", "exchangeTimezoneName": "America/New_York"},
               "timestamp": [1735689600], "indicators": {"quote": [{"close": [101.]}]}}], "error": None}}
    result = yahoo_metadata(payload)
    assert result["vendor_metadata"]["symbol"] == "PL=F"
    assert result["bar_completion_verified"] is False
    assert result["roll_methodology_verified"] is False
    assert "indicators" not in result


@pytest.mark.parametrize("symbol,instrument", [("GC=F", "FUTURE"), ("PL=F", "EQUITY")])
def test_wrong_instrument_is_rejected(symbol, instrument):
    with pytest.raises(ValueError, match="instrument"):
        yahoo_metadata({"chart": {"result": [{"meta": {"symbol": symbol, "instrumentType": instrument}}]}})


def test_provider_error_is_rejected():
    with pytest.raises(ValueError, match="provider"):
        yahoo_metadata({"chart": {"result": None, "error": {"description": "unavailable"}}})


def test_current_contract_specs_do_not_verify_historical_calendar_or_yahoo_roll():
    result = cme_metadata({"ProductID": 446, "ProductName": "Platinum Futures",
                           "ContractUnit": "50 troy ounces", "PriceQuotation": "U.S. dollars per troy ounce",
                           "TradingHours": {"vandhr": [{"venue": "CME Globex:", "hours": "17:00 to 16:00 CT"}]}})
    assert result["official_fields"]["ContractUnit"] == "50 troy ounces"
    assert result["historical_holiday_calendar_verified"] is False
    assert result["yahoo_roll_methodology_verified"] is False


def test_wrong_cme_product_is_rejected():
    with pytest.raises(ValueError, match="product"):
        cme_metadata({"ProductID": 123, "ProductName": "Other product"})
