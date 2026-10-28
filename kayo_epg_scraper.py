"""Generate Kayo XMLTV from the public service used by the current Kayo site."""
from collections import Counter
from datetime import datetime, timedelta, time
import logging
from urllib.parse import urlencode, quote
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from epg_runtime import run_generator

# --- Configuration ---

# 1. Channels Configuration:
# Updated to only include the channels you specified.
CHANNELS_CONFIG = {
    "501": {"id_num": "4k.6.kayo", "display_name": "Kayo UHD 6 (Cricket)"},
    "502": {"id_num": "4k.2.kayo", "display_name": "Kayo UHD 2 (Footy 2)"},
    "503": {"id_num": "4k.3.kayo", "display_name": "Kayo UHD 3 (League)"},
    "504": {"id_num": "4k.1.kayo", "display_name": "Kayo UHD 1 (Footy 1)"},
    "505": {"id_num": "4k.5.kayo", "display_name": "Kayo UHD 5 (Netball)"},
    "506": {"id_num": "4k.4.kayo", "display_name": "Kayo UHD 4 (F1)"},
    }



# Updated mapping for the specified channels
KAYO_CHANNEL_MAP = {
    "fsa501": "501",
    "fsa502": "502",
    "fsa503": "503",
    "fsa504": "504",
    "fsa505": "505",
    "fsa506": "506",
}

# 2. EPG Duration:
# Set the total number of days of EPG data to fetch.
TOTAL_DAYS_TO_FETCH = 14

# 3. Icon Mapping (for Channels):
# Icons are mapped using the keys from CHANNELS_CONFIG.
ICON_MAP = {
    "501": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.501.png", # Cricket
    "502": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.504.png", # Footy 2
    "503": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.502.png", # League
    "504": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.504.png", # Footy 1
    "505": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.505.png", # Netball
    "506": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.506.png", # F1
}
DEFAULT_ICON = "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/4k.kayo.50X.png"

# --- End Configuration ---

SYDNEY = ZoneInfo("Australia/Sydney")
STARTUP_URL = "https://startup.core.indazn.com/v1/main/web?Platform=web&LandingPageKey=generic&Brand=kayo"
HEADERS = {"Accept": "application/json", "Origin": "https://kayosports.com.au",
           "Referer": "https://kayosports.com.au/", "User-Agent": "Kayo-EPG/2.0"}


def date_windows(first_day, days):
    """The API accepts at most seven inclusive days and one UTC offset per call."""
    current = first_day
    remaining = days
    while remaining:
        offset = int(datetime.combine(current, time(), SYDNEY).utcoffset().total_seconds() / 60)
        count = 1
        while count < min(remaining, 7):
            following = datetime.combine(current + timedelta(days=count), time(), SYDNEY)
            if following.utcoffset().total_seconds() / 60 != offset:
                break
            count += 1
        yield current, current + timedelta(days=count - 1), offset
        current += timedelta(days=count)
        remaining -= count


def fetch_epg_data(*, days=TOTAL_DAYS_TO_FETCH, client):
    startup = client.get(STARTUP_URL, headers=HEADERS).json()
    if not isinstance(startup, dict):
        raise ValueError("Invalid Kayo startup response")
    region = startup.get("Region", {})
    if not region.get("isAllowed") or region.get("Country", "").lower() != "au":
        raise ValueError("Kayo startup did not allow the Australian catalogue")
    services = startup.get("ServiceDictionary", {})
    # Pin the schema version we parse; discover its host/path from the site.
    endpoint = services.get("EpgWithDateRange", {}).get("Versions", {}).get("v6", {}).get("ServicePath")
    image_base = services.get("img", {}).get("Versions", {}).get("v3", {}).get("ServicePath")
    if not endpoint or not endpoint.startswith("https://"):
        raise ValueError("Kayo startup is missing the v6 date-range EPG service")

    today = datetime.now(SYDNEY).date()
    all_events = []
    for first, last, offset in date_windows(today, days):
        params = {"country": "au", "languageCode": "en", "openBrowse": "true",
                  "timeZoneOffset": offset, "startDate": first.isoformat(),
                  "endDate": last.isoformat(), "brand": "kayo"}
        url = endpoint + "?" + urlencode(params)
        payload = client.get(url, headers=HEADERS).json()
        if not isinstance(payload, dict) or not isinstance(payload.get("Tiles"), list):
            raise ValueError(f"Kayo EPG {first}–{last} is missing the Tiles list")
        if payload.get("StartDate") != first.isoformat() or payload.get("EndDate") != last.isoformat():
            raise ValueError("Kayo returned a different date range; refusing to publish it")
        for tile in payload["Tiles"]:
            if not isinstance(tile, dict):
                raise ValueError("Kayo EPG contains a malformed tile")
            tile = dict(tile)
            image_id = (tile.get("Image") or {}).get("Id")
            if image_base and image_id:
                tile["image_url"] = (f"{image_base.rstrip('/')}/none/{quote(image_id, safe='')}"
                                     "/fill/none/top/none/80/720/405/webp/image?brand=kayo")
            all_events.append(tile)
        logging.info("Kayo %s through %s: %d tiles (generated %s)",
                     first, last, len(payload["Tiles"]), payload.get("Generated"))
    return all_events


def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError(f"Timestamp has no timezone: {value}")
    return parsed


def convert_to_xmltv(events_data):
    root = ET.Element("tv", {"generator-info-name": "Kayo EPG Scraper"})
    for channel_tag, channel_info in CHANNELS_CONFIG.items():
        channel = ET.SubElement(root, "channel", {"id": f"{channel_info['id_num']}.{channel_tag}"})
        ET.SubElement(channel, "display-name").text = channel_info["display_name"]
        ET.SubElement(channel, "icon", {"src": ICON_MAP.get(channel_tag, DEFAULT_ICON)})

    programmes = []
    seen = set()
    unmatched = Counter()
    for item in events_data:
        provider = (item.get("LinearProvider") or "").lower()
        channel_tag = KAYO_CHANNEL_MAP.get(provider)
        if channel_tag not in CHANNELS_CONFIG:
            unmatched[provider or "(none)"] += 1
            continue
        asset_id = item.get("AssetId") or item.get("EventId")
        if not asset_id or not item.get("Title") or not item.get("Start"):
            raise ValueError(f"Mapped Kayo event has missing identity/title/start: {asset_id}")
        start = parse_timestamp(item["Start"])
        end = parse_timestamp(item["End"]) if item.get("End") else None
        if end is not None and end <= start:
            raise ValueError(f"Kayo event {asset_id} has an invalid end time")
        key = (provider, asset_id, start)
        if key in seen:
            continue
        seen.add(key)
        programmes.append((start, channel_tag, str(asset_id), end, item))

    counts = Counter()
    unknown_end = 0
    for start, channel_tag, asset_id, end, item in sorted(programmes, key=lambda p: p[:3]):
        info = CHANNELS_CONFIG[channel_tag]
        attributes = {"start": start.astimezone(SYDNEY).strftime("%Y%m%d%H%M%S %z"),
                      "channel": f"{info['id_num']}.{channel_tag}"}
        # ExpirationDate is an asset expiry, not a broadcast end. XMLTV permits
        # an absent stop attribute. Do not invent two-hour programmes.
        if end is not None:
            attributes["stop"] = end.astimezone(SYDNEY).strftime("%Y%m%d%H%M%S %z")
        else:
            unknown_end += 1
        programme = ET.SubElement(root, "programme", attributes)
        competition = (item.get("Competition") or {}).get("Title")
        title = f"{competition}: {item['Title']}" if competition else item["Title"]
        ET.SubElement(programme, "title", {"lang": "en"}).text = title
        season = (item.get("TournamentCalendar") or {}).get("Title")
        if season:
            ET.SubElement(programme, "sub-title", {"lang": "en"}).text = season
        if item.get("Description"):
            ET.SubElement(programme, "desc", {"lang": "en"}).text = item["Description"]
        if item.get("image_url"):
            ET.SubElement(programme, "icon", {"src": item["image_url"]})
        counts[channel_tag] += 1
    for channel_tag in CHANNELS_CONFIG:
        logging.info("Channel %s: %d programmes", channel_tag, counts[channel_tag])
    logging.info("Ignored providers outside the configured mapping: %s", dict(unmatched))
    if unknown_end:
        logging.warning("%d programmes have no source end time; XMLTV stop omitted", unknown_end)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True).decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(run_generator(fetch_epg_data, convert_to_xmltv,
                                   days=TOTAL_DAYS_TO_FETCH, output="kayo_guide.xml",
                                   max_seconds=300))
