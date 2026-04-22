import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import pytz
import time
import re

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


def fetch_epg_data():
    """
    Fetches EPG data for the specified number of days from the Kayo Sports API.
    """
    base_url = 'https://api.kayosports.com.au/v3/content/types/landing/names/fixtures'
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-AU,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Origin': 'https://kayosports.com.au',
        'Pragma': 'no-cache',
        'Referer': 'https://kayosports.com.au/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }

    now = datetime.now(timezone.utc)
    all_events = []

    print(f"Starting EPG fetch for {TOTAL_DAYS_TO_FETCH} days...")

    for day in range(TOTAL_DAYS_TO_FETCH):
        target_date = now + timedelta(days=day)
        date_str = target_date.strftime('%Y-%m-%dT00:00:00Z')
        url = f'{base_url}?from={date_str}'

        print(f"Fetching data for day {day + 1}/{TOTAL_DAYS_TO_FETCH} ({target_date.strftime('%Y-%m-%d')})...")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            daily_data = response.json()

            if "panels" in daily_data:
                for panel in daily_data["panels"]:
                    if "contents" in panel:
                        all_events.extend(panel["contents"])

            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"    Error fetching data for day {day + 1}: {e}")
        except json.JSONDecodeError:
            print(f"    Error decoding JSON for day {day + 1}. Skipping.")

    return all_events


def parse_duration(duration_str):
    """
    Parses a duration string like "4h 40m" into total minutes.
    """
    hours = 0
    minutes = 0
    
    hour_match = re.search(r'(\d+)h', duration_str)
    if hour_match:
        hours = int(hour_match.group(1))

    minute_match = re.search(r'(\d+)m', duration_str)
    if minute_match:
        minutes = int(minute_match.group(1))

    return (hours * 60) + minutes


def convert_to_xmltv(events_data):
    """
    Converts the fetched Kayo JSON data into a standardized XMLTV format.
    """
    if not events_data:
        print("Error: No valid JSON data to convert.")
        return None

    local_tz = pytz.timezone('Australia/Sydney')
    root = ET.Element("tv", {"generator-info-name": "Kayo EPG Scraper"})

    print("\nGenerating XMLTV file...")
    # --- Create Channel Elements ---
    for channel_tag, channel_info in CHANNELS_CONFIG.items():
        xml_channel_id = f"{channel_info['id_num']}.{channel_tag}"
        channel_el = ET.SubElement(root, "channel", {"id": xml_channel_id})
        ET.SubElement(channel_el, "display-name").text = channel_info['display_name']
        ET.SubElement(channel_el, "icon", {"src": ICON_MAP.get(channel_tag, DEFAULT_ICON)})

    # --- Create Programme Elements ---
    print(f"Processing {len(events_data)} total content items...")
    processed_asset_ids = set()


    for item in events_data:
        try:
            if item.get("contentType") != "video" or "data" not in item:
                continue
            
            data = item["data"]
            asset_id = data.get("id")
            clickthrough = data.get("clickthrough", {})
            content_display = data.get("contentDisplay", {})
            
            if not asset_id or asset_id in processed_asset_ids:
                continue

            kayo_channel_name = clickthrough.get("channel")
            if not kayo_channel_name:
                continue

            channel_tag = KAYO_CHANNEL_MAP.get(kayo_channel_name.lower())
            if not channel_tag or channel_tag not in CHANNELS_CONFIG:
                continue
                
            channel_info = CHANNELS_CONFIG[channel_tag]
            xml_channel_id = f"{channel_info['id_num']}.{channel_tag}"

            start_time_utc_str = clickthrough.get("transmissionTime")
            if not start_time_utc_str:
                continue
            
            start_dt_utc = datetime.fromisoformat(start_time_utc_str.replace('Z', '+00:00'))
            
            duration_minutes = 120
            if "infoLine" in content_display:
                for info_item in content_display["infoLine"]:
                    if info_item.get("type") == "length":
                        duration_minutes = parse_duration(info_item.get("value", ""))
                        break
            
            end_dt_utc = start_dt_utc + timedelta(minutes=duration_minutes)
            
            start_dt_local = start_dt_utc.astimezone(local_tz)
            end_dt_local = end_dt_utc.astimezone(local_tz)

            start_time_str = start_dt_local.strftime('%Y%m%d%H%M%S %z')
            end_time_str = end_dt_local.strftime('%Y%m%d%H%M%S %z')

            programme_el = ET.SubElement(root, "programme", {
                "start": start_time_str,
                "stop": end_time_str,
                "channel": xml_channel_id
            })

            # --- Mapped Titles, Descriptions, and Images ---
            series_name = clickthrough.get('seriesName', '')
            title = clickthrough.get('title', 'No Title')
            ET.SubElement(programme_el, "title", {"lang": "en"}).text = f"{series_name}: {title}"
            
            season_name = clickthrough.get('seasonName')
            if season_name:
                 ET.SubElement(programme_el, "sub-title", {"lang": "en"}).text = season_name

            if "synopsis" in content_display and content_display["synopsis"]:
                ET.SubElement(programme_el, "desc", {"lang": "en"}).text = content_display["synopsis"]

            if "images" in content_display and "heroPortrait_m2" in content_display["images"]:
                img_url = content_display["images"]["heroPortrait_m2"].replace('${WIDTH}', '720')
                img_url = re.sub(r'[&?]location=[^&]*', '', img_url)
                ET.SubElement(programme_el, "icon", {"src": img_url})

            processed_asset_ids.add(asset_id)

        except KeyError as e:
            print(f"    Skipping item due to missing key: {e}")
        except Exception as e:
            print(f"    An unexpected error occurred while processing an item: {e}")

    ET.indent(root, space="  ", level=0)
    xml_string = ET.tostring(root, encoding="UTF-8", xml_declaration=True).decode('utf-8')
    return xml_string


# --- Main Execution ---
if __name__ == "__main__":
    epg_data = fetch_epg_data()

    if epg_data:
        xmltv_output = convert_to_xmltv(epg_data)

        if xmltv_output:
            output_filename = "kayo_guide.xml"
            try:
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(xmltv_output)
                print(f"\n✅ XMLTV data successfully generated and saved to {output_filename}")
            except IOError as e:
                print(f"\n❌ Error saving file: {e}")
    else:
        print("\n❌ No programme data was fetched. The XML file was not generated.")
