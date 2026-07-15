from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from astroquery.simbad import Simbad
from astropy.coordinates import SkyCoord
import astropy.units as u


INPUT_FILE = Path("data/astronomy-targets-master-stage3a.json")
OUTPUT_FILE = Path("data/astronomy-targets-master-stage3b-coordinates.json")
REVIEW_FILE = Path("data/astronomy-targets-coordinate-review.json")


# Explicit overrides are important for targets whose practical imaging
# identity differs from the catalogue component stored as primary.
SIMBAD_LOOKUP_OVERRIDES = {
    "m-16-eagle-nebula": "M 16",
    "m-8-lagoon-nebula": "M 8",
    "sh2-142": "Sh2-142",
    "vdb-141": "VDB 141",
    "ic-1396a": "IC 1396A",
    "ic-5070": "IC 5070",
}


def text_value(value: Any) -> str | None:
    """Convert an Astropy table value into a normal string."""
    if value is None:
        return None

    # Masked Astropy values should be treated as missing.
    if getattr(value, "mask", False):
        return None

    if isinstance(value, bytes):
        return value.decode("utf-8").strip()

    return str(value).strip()


def query_simbad(identifier: str) -> dict[str, Any] | None:
    """Query one object and return normalized coordinate data."""
    result = Simbad.query_object(identifier)

    if result is None or len(result) == 0:
        return None

    if len(result) != 1:
        raise ValueError(
            f"SIMBAD returned {len(result)} rows for {identifier!r}; "
            "manual review is required."
        )

    row = result[0]
    columns = {name.lower(): name for name in result.colnames}

    main_id_column = columns.get("main_id")
    ra_column = columns.get("ra")
    dec_column = columns.get("dec")

    if not main_id_column or not ra_column or not dec_column:
        raise KeyError(
            f"Unexpected SIMBAD columns for {identifier!r}: "
            f"{result.colnames}"
        )

    main_id = text_value(row[main_id_column])
    ra_value = row[ra_column]
    dec_value = row[dec_column]

    # Current Astroquery SIMBAD responses commonly provide RA and Dec
    # as degree-valued table columns. This branch also tolerates strings.
    try:
        ra_deg = float(ra_value)
        dec_deg = float(dec_value)
        coordinate = SkyCoord(
            ra=ra_deg * u.deg,
            dec=dec_deg * u.deg,
            frame="icrs",
        )
    except (TypeError, ValueError):
        coordinate = SkyCoord(
            f"{text_value(ra_value)} {text_value(dec_value)}",
            unit=(u.hourangle, u.deg),
            frame="icrs",
        )
        ra_deg = coordinate.ra.deg
        dec_deg = coordinate.dec.deg

    return {
        "lookup_identifier": identifier,
        "resolved_main_id": main_id,
        "frame": "ICRS",
        "equinox": "J2000",
        "ra_deg": round(ra_deg, 8),
        "dec_deg": round(dec_deg, 8),
        "ra_display": coordinate.ra.to_string(
            unit=u.hourangle,
            sep="hms",
            precision=2,
            pad=True,
        ),
        "dec_display": coordinate.dec.to_string(
            unit=u.deg,
            sep="dms",
            precision=1,
            alwayssign=True,
            pad=True,
        ),
        "source": "SIMBAD",
    }


def enrich_catalogue() -> None:
    catalogue = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    review_items: list[dict[str, Any]] = []

    for target in catalogue["targets"]:
        target_id = target["id"]
        identifier = SIMBAD_LOOKUP_OVERRIDES.get(
            target_id,
            target["primary_catalog_id"],
        )

        try:
            coordinate_data = query_simbad(identifier)

            if coordinate_data is None:
                target["coordinates"] = None
                target["coordinate_review_status"] = "not_found"
                review_items.append({
                    "id": target_id,
                    "display_name": target["display_name"],
                    "lookup_identifier": identifier,
                    "reason": "SIMBAD returned no result",
                })
            else:
                target["coordinates"] = coordinate_data
                target["coordinate_review_status"] = "pending_verification"

        except Exception as exc:
            target["coordinates"] = None
            target["coordinate_review_status"] = "query_error"
            review_items.append({
                "id": target_id,
                "display_name": target["display_name"],
                "lookup_identifier": identifier,
                "reason": str(exc),
            })

        # Be polite to the shared public service.
        time.sleep(0.25)

    catalogue["schema_version"] = "0.3-draft"
    catalogue["stage"] = "3B.1_simbad_coordinates"
    catalogue["coordinate_summary"] = {
        "source": "SIMBAD",
        "targets_processed": len(catalogue["targets"]),
        "targets_needing_review": len(review_items),
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(catalogue, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    REVIEW_FILE.write_text(
        json.dumps(review_items, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote enriched catalogue: {OUTPUT_FILE}")
    print(f"Wrote review queue: {REVIEW_FILE}")
    print(f"Targets requiring review: {len(review_items)}")


if __name__ == "__main__":
    enrich_catalogue()