"""Bounded public-source probes through inherited proxy and verified TLS."""
from __future__ import annotations

import hashlib
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE_URLS = {
    "cme_contract": "https://www.cmegroup.com/markets/metals/precious/platinum.contractSpecs.html",
    "cme_specs": "https://www.cmegroup.com/CmeWS/mvc/ContractSpecs/List/productId/446",
    "cme_holidays": "https://www.cmegroup.com/tools-information/holiday-calendar.html",
    "cme_settlement": "https://www.cmegroup.com/confluence/display/EPICSANDBOX/Platinum",
    "yahoo_quote": "https://finance.yahoo.com/quote/PL%3DF/",
    "yahoo_chart": "https://query1.finance.yahoo.com/v8/finance/chart/PL%3DF?range=5d&interval=1d",
}


def yahoo_metadata(payload: dict) -> dict:
    chart = payload.get("chart", {}) if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise ValueError("invalid provider chart")
    results = chart.get("result")
    if chart.get("error") or not isinstance(results, list) or len(results) != 1:
        raise ValueError("provider error or ambiguous chart result")
    if not isinstance(results[0], dict) or not isinstance(results[0].get("meta"), dict):
        raise ValueError("invalid provider metadata")
    meta = results[0]["meta"]
    if meta.get("symbol") != "PL=F" or meta.get("instrumentType") != "FUTURE":
        raise ValueError("provider instrument does not match PL=F futures")
    fields = ("symbol", "currency", "instrumentType", "exchangeTimezoneName", "exchangeName",
              "firstTradeDate", "regularMarketTime", "dataGranularity", "priceHint")
    timestamps = results[0].get("timestamp", [])
    latest = max(timestamps) if isinstance(timestamps, list) and timestamps else None
    return {"vendor_metadata": {k: meta[k] for k in fields if k in meta},
            "last_chart_timestamp_utc": datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest is not None else None,
            "bar_completion_verified": False, "roll_methodology_verified": False,
            "license_verified": False,
            "warning": "Vendor metadata and timezone labels do not certify bar availability, settlement definition or rollover."}


def cme_metadata(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("ProductID") != 446 or payload.get("ProductName") != "Platinum Futures":
        raise ValueError("CME product does not match Platinum Futures product 446")
    fields = ("ProductID", "ProductName", "ContractUnit", "PriceQuotation", "TradingHours",
              "SettlementMethod", "TerminationOfTrading", "SettlementProcedures", "ExchangeRulebook")
    return {"official_fields": {k: payload[k] for k in fields if k in payload},
            "historical_holiday_calendar_verified": False,
            "yahoo_roll_methodology_verified": False,
            "warning": "Current exchange specifications are not a historical holiday calendar or a Yahoo continuous-contract policy."}


def probe_sources(cache_directory: Path) -> dict:
    cache_directory.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, url in SOURCE_URLS.items():
        record = {"url": url, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "authoritative_content_verified": False}
        try:
            request = Request(url, headers={"User-Agent": "platinum-data-audit/0.1"})
            with urlopen(request, timeout=15, context=ssl.create_default_context()) as response:
                body = response.read(3*1024*1024+1)
                if len(body) > 3*1024*1024:
                    raise ValueError("source document exceeds bounded cache size")
                record.update(http_status=response.status, bytes=len(body),
                              content_sha256=hashlib.sha256(body).hexdigest(),
                              status="retrieved_review_required")
            (cache_directory / f"{name}.body").write_bytes(body)
            if name == "yahoo_chart":
                record["chart_metadata"] = yahoo_metadata(json.loads(body))
            if name == "cme_specs":
                record["contract_metadata"] = cme_metadata(json.loads(body))
                record["authoritative_content_verified"] = True
        except HTTPError as error:
            record.update(status="http_failure", http_status=error.code)
        except (URLError, OSError):
            record.update(status="proxy_or_transport_failure", http_status=None)
        except (ValueError, KeyError, TypeError):
            record.update(status="invalid_provider_response", http_status=None)
        records[name] = record
    return records
