"""Derive compact deterministic company memory from evaluation-reference.jsonl.

Safety contract: Reads ONLY non-holdout Gold rows from evaluation-reference.jsonl.
Never reads evaluation-ground-truth.jsonl. Never exposes source_move_id, checksums,
or any holdout facts. Produces compact JSON/text suitable for LLM context that
conveys company conventions without leaking evaluation data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any


class CompanyMemoryError(RuntimeError):
    """Raised when company memory cannot be derived safely."""


class CompanyMemory:
    """Deterministic consensus derived ONLY from non-holdout reference rows.

    In-memory catalogs (never exposed to LLM as-is, only via hints):
    - account_catalog: {code: {code, names_set, debit_count, credit_count}}
    - journal_move_type_pairs: {(journal, move_type): count}
    - move_type_journal_pairs: {(move_type, journal): count}
    - currency_counter: {code: count}
    - tax_counter: {name: count}
    - partner_presence: count of cases with non-null partner
    - analytic_presence: count of cases with non-empty analytic
    - line_count_distribution: [count1, count2, ...]

    Compact LLM-suitable output (build_memory_hints):
    - Top journals with move_type conditional confidence
    - Top accounts with debit/credit direction preference
    - Currencies and taxes
    - Partner/analytic presence rates
    - Line count guidance
    """

    def __init__(
        self,
        company_name: str = "Unknown",
        contract_version: str = "1.0",
    ) -> None:
        self.company_name = company_name
        self.contract_version = contract_version
        self.total_reference_cases = 0

        # Full in-memory catalogs
        self.account_catalog: dict[str, dict[str, Any]] = {}
        self.journal_move_type_pairs: Counter[tuple[str, str]] = Counter()
        self.move_type_journal_pairs: Counter[tuple[str, str]] = Counter()

        self.currency_counter: Counter[str] = Counter()
        self.tax_counter: Counter[str] = Counter()
        self.partner_presence = 0
        self.analytic_presence = 0
        self.line_counts: list[int] = []

        # Debit/credit direction tracking
        self.account_debit_count: Counter[str] = Counter()
        self.account_credit_count: Counter[str] = Counter()
        self.move_type_debit_count: Counter[str] = Counter()
        self.move_type_credit_count: Counter[str] = Counter()

        # Summary counters (for quick access)
        self.journals: Counter[str] = Counter()
        self.move_types: Counter[str] = Counter()

    def to_dict(self) -> dict[str, Any]:
        """Serialize full memory to JSON (for testing/storage).

        Convert tuple-keyed Counters to JSON-safe string-keyed dicts.
        """
        # Convert tuple-keyed counters to string-keyed dicts
        # (e.g., ("MISC", "entry") -> "MISC|entry")
        journal_move_pairs_json = {
            f"{journal}|{move_type}": count
            for (journal, move_type), count in (
                self.journal_move_type_pairs.items()
            )
        }
        move_type_journal_pairs_json = {
            f"{move_type}|{journal}": count
            for (move_type, journal), count in (
                self.move_type_journal_pairs.items()
            )
        }

        return {
            "company_name": self.company_name,
            "contract_version": self.contract_version,
            "total_reference_cases": self.total_reference_cases,
            "account_catalog": self.account_catalog,
            "journal_move_type_pairs": journal_move_pairs_json,
            "move_type_journal_pairs": move_type_journal_pairs_json,
            "currency_counter": dict(self.currency_counter),
            "tax_counter": dict(self.tax_counter),
            "partner_presence": self.partner_presence,
            "analytic_presence": self.analytic_presence,
            "line_count_distribution": self.line_counts,
            "journals": dict(self.journals),
            "move_types": dict(self.move_types),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CompanyMemory:
        """Deserialize memory from JSON, parsing string keys back to tuples."""
        mem = CompanyMemory(
            company_name=data.get("company_name", "Unknown"),
            contract_version=data.get("contract_version", "1.0"),
        )
        mem.total_reference_cases = data.get("total_reference_cases", 0)
        mem.account_catalog = data.get("account_catalog", {})

        # Parse string-keyed dicts back to tuple-keyed Counters
        journal_move_dict = data.get("journal_move_type_pairs", {})
        mem.journal_move_type_pairs = Counter(
            {
                tuple(key.split("|", 1)): count
                for key, count in journal_move_dict.items()
                if "|" in key
            }
        )

        move_type_journal_dict = data.get("move_type_journal_pairs", {})
        mem.move_type_journal_pairs = Counter(
            {
                tuple(key.split("|", 1)): count
                for key, count in move_type_journal_dict.items()
                if "|" in key
            }
        )

        mem.currency_counter = Counter(data.get("currency_counter", {}))
        mem.tax_counter = Counter(data.get("tax_counter", {}))
        mem.partner_presence = data.get("partner_presence", 0)
        mem.analytic_presence = data.get("analytic_presence", 0)
        mem.line_counts = data.get("line_count_distribution", [])
        mem.journals = Counter(data.get("journals", {}))
        mem.move_types = Counter(data.get("move_types", {}))
        return mem


def derive_company_memory(
    reference_rows: list[dict[str, Any]],
) -> CompanyMemory:
    """Extract deterministic memory from non-holdout reference pool rows ONLY.

    Args:
        reference_rows: Rows from evaluation-reference.jsonl (non-holdout Gold)

    Returns:
        CompanyMemory with catalogs and frequency counts

    Raises:
        CompanyMemoryError: If reference pool empty or malformed
    """
    if not reference_rows:
        raise CompanyMemoryError("Reference pool is empty")

    mem = CompanyMemory(
        company_name="GITC Reference Derived",
        contract_version=_extract_contract_version(reference_rows),
    )
    mem.total_reference_cases = len(reference_rows)

    # Per-case processors
    for row in reference_rows:
        target = row.get("target")
        if not isinstance(target, dict):
            continue

        # Extract journal
        journal = target.get("journal")
        journal_name = None
        if isinstance(journal, dict):
            journal_name = journal.get("name") or journal.get("code")
        if journal_name:
            mem.journals[journal_name] += 1

        # Extract move_type
        move_type = target.get("move_type")
        if isinstance(move_type, str):
            mem.move_types[move_type] += 1

            # Track journal -> move_type pair (for conditional confidence)
            if journal_name:
                mem.journal_move_type_pairs[(journal_name, move_type)] += 1
                mem.move_type_journal_pairs[(move_type, journal_name)] += 1

        # Partner presence
        partner = target.get("partner")
        if partner is not None and partner:
            mem.partner_presence += 1

        # Currency
        currency = target.get("currency")
        if isinstance(currency, dict):
            currency_code = currency.get("name") or currency.get("code")
            if currency_code:
                mem.currency_counter[currency_code] += 1

        # Taxes
        taxes = target.get("taxes")
        if isinstance(taxes, list):
            for tax in taxes:
                if isinstance(tax, dict):
                    tax_name = tax.get("name")
                    if tax_name:
                        mem.tax_counter[tax_name] += 1

        # Process journal entry lines
        lines = target.get("journal_entry")
        if isinstance(lines, list):
            mem.line_counts.append(len(lines))

            for line in lines:
                if not isinstance(line, dict):
                    continue

                account_code = line.get("account_code")
                if not account_code:
                    continue

                # Track account names (actual GITC names from history)
                account_name = line.get("account_name")

                # Debit/credit direction
                debit_val = _to_decimal(line.get("debit"))
                credit_val = _to_decimal(line.get("credit"))

                if debit_val > 0:
                    mem.account_debit_count[account_code] += 1
                    if move_type:
                        mem.move_type_debit_count[move_type] += 1

                if credit_val > 0:
                    mem.account_credit_count[account_code] += 1
                    if move_type:
                        mem.move_type_credit_count[move_type] += 1

                # Build account catalog (all accounts, with names)
                if account_code not in mem.account_catalog:
                    mem.account_catalog[account_code] = {
                        "code": account_code,
                        "names": set(),
                        "debit_count": 0,
                        "credit_count": 0,
                        "move_type_usage": Counter(),
                    }

                if account_name:
                    mem.account_catalog[account_code]["names"].add(
                        account_name
                    )

                mem.account_catalog[account_code]["debit_count"] += (
                    1 if debit_val > 0 else 0
                )
                mem.account_catalog[account_code]["credit_count"] += (
                    1 if credit_val > 0 else 0
                )
                if move_type:
                    mem.account_catalog[account_code]["move_type_usage"][
                        move_type
                    ] += 1

            # Check for analytic distribution on this case
            for line in lines:
                if isinstance(line, dict):
                    analytic = line.get("analytic_distribution")
                    if analytic is not None and analytic:
                        mem.analytic_presence += 1
                        break

    # Normalize account names to sorted lists (for JSON serialization)
    for code, info in mem.account_catalog.items():
        info["names"] = sorted(info["names"])
        info["move_type_usage"] = dict(info["move_type_usage"])

    return mem


def _extract_contract_version(
    reference_rows: list[dict[str, Any]],
) -> str:
    """Extract contract version from first row with one."""
    for row in reference_rows:
        version = row.get("contract_version")
        if isinstance(version, str) and version:
            return version
    return "1.0"


def _to_decimal(value: Any) -> Decimal:
    """Convert value to Decimal, return 0.00 on error."""
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def build_memory_hints(memory: CompanyMemory) -> str:
    """Build compact LLM-suitable text hints from memory.

    Conveys:
    - Top journals and their move_type conditional frequencies
    - Top accounts with debit/credit direction preferences
    - Currency and tax candidates (with frequency)
    - Partner/analytic presence rates
    - Line count guidance

    No amounts, no move IDs, no holdout facts exposed.
    """
    hints: list[str] = []

    # Journal → move_type conditional confidence
    if memory.journal_move_type_pairs:
        journal_pairs = defaultdict(list)
        for (journal, move_type), count in (
            memory.journal_move_type_pairs.items()
        ):
            total_for_journal = sum(
                c
                for (j, mt), c in (
                    memory.journal_move_type_pairs.items()
                )
                if j == journal
            )
            confidence = (
                round(count / total_for_journal, 2)
                if total_for_journal > 0
                else 0.0
            )
            journal_pairs[journal].append(
                (move_type, confidence, count)
            )

        for journal in sorted(journal_pairs.keys())[:3]:
            pairs_str = ", ".join(
                f"{mt} ({conf})"
                for mt, conf, _ in sorted(
                    journal_pairs[journal],
                    key=lambda x: -x[1],
                )[:2]
            )
            hints.append(
                f"Journal {journal}: move_types {pairs_str}"
            )

    # Top 5 accounts with debit/credit preference
    if memory.account_catalog:
        top_accounts = sorted(
            memory.account_catalog.items(),
            key=lambda x: x[1]["debit_count"] + x[1]["credit_count"],
            reverse=True,
        )[:5]
        account_hints = []
        for code, info in top_accounts:
            dcount = info["debit_count"]
            ccount = info["credit_count"]
            total = dcount + ccount
            if total > 0:
                debit_pref = round(dcount / total, 2)
                credit_pref = round(ccount / total, 2)
                pref = (
                    f"debit {debit_pref}"
                    if debit_pref > credit_pref
                    else f"credit {credit_pref}"
                )
                names_str = (
                    info["names"][0]
                    if info["names"]
                    else code
                )
                account_hints.append(
                    f"{code} ({names_str}, {pref})"
                )
        if account_hints:
            hints.append(
                f"Top accounts: {'; '.join(account_hints)}"
            )

    # Currency candidates
    if memory.currency_counter:
        top_currency = memory.currency_counter.most_common(1)[0]
        hints.append(
            f"Currency: {top_currency[0]} ({top_currency[1]} cases)"
        )

    # Tax candidates
    if memory.tax_counter:
        top_taxes = memory.tax_counter.most_common(2)
        tax_str = ", ".join(f"{t[0]}" for t in top_taxes)
        hints.append(f"Taxes: {tax_str}")

    # Partner and analytic presence
    partner_pct = (
        round(
            100
            * memory.partner_presence
            / memory.total_reference_cases
        )
        if memory.total_reference_cases > 0
        else 0
    )
    analytic_pct = (
        round(
            100
            * memory.analytic_presence
            / memory.total_reference_cases
        )
        if memory.total_reference_cases > 0
        else 0
    )
    hints.append(
        f"Partner presence: {partner_pct}%; Analytic: {analytic_pct}%"
    )

    # Line count guidance
    if memory.line_counts:
        sorted_counts = sorted(memory.line_counts)
        min_lines = sorted_counts[0]
        max_lines = sorted_counts[-1]
        median_lines = sorted_counts[len(sorted_counts) // 2]
        hints.append(
            f"Entry sizes: {min_lines}–{max_lines} lines "
            f"(median {median_lines})"
        )

    return " ".join(hints)


# Type alias for use in grounded_runner
MemoryType = CompanyMemory
