import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import pytz
import time

# --- Configuration ---

# 1. Channels Configuration:
# Define the channels you want to include.
# - Key (e.g., "FAF"): The channel tag from the Foxtel data source.
# - "id_num": The numeric part of the channel ID you want in your XML file.
# - "display_name": The full name you want to see in your EPG client.
CHANNELS_CONFIG = {
    "FS1": {"id_num": "501", "display_name": "FOX 501"},
    "SP2": {"id_num": "502", "display_name": "FOX 502"},
    "FS3": {"id_num": "503", "display_name": "FOX 503"},
    "FAF": {"id_num": "504", "display_name": "FOX 504"},
    "FSP": {"id_num": "505", "display_name": "FOX 505"},
    "SPS": {"id_num": "506", "display_name": "FOX 506"},
    "FSS": {"id_num": "507", "display_name": "FOX 507"},

    # Example for adding another channel:
    # "SKY": {"id_num": "600", "display_name": "Sky News"}
}

# 2. EPG Duration:
# Set the total number of days of EPG data to fetch.
TOTAL_DAYS_TO_FETCH = 21

# 3. Icon Mapping (for Channels):
# The keys here must match the keys in CHANNELS_CONFIG (e.g., "FAF").
ICON_MAP = {
    "FS1": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Cricket.png",
    "FAF": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Footy.png",
    "SP2": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20League.png",
    "FS3": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20503.png",
    "FSP": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20505.png",
    "SPS": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20506.png",
    "FSS": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20More.png",
    # "SKY": "https://example.com/sky_logo.png",
}
DEFAULT_ICON = "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports.png"

# --- End Configuration ---


def fetch_epg_data():
    """
    Fetches EPG data by first getting the grid in 6-hour chunks,
    then fetching detailed data for each individual event.
    """
    grid_base_url = 'https://www.foxtel.com.au/webepg/ws/foxtel/grid/events'
    event_base_url = 'https://www.foxtel.com.au/webepg/ws/foxtel/event/'

    headers = {
        'Accept': 'application/json; charset=utf-8',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://www.foxtel.com.au/tv-guide/grid',
    }

    now = datetime.now(timezone.utc)
    total_duration_hours = TOTAL_DAYS_TO_FETCH * 24
    chunk_duration_hours = 6
    num_iterations = total_duration_hours // chunk_duration_hours

    # Initialize the aggregated data structure based on the keys from the new config
    aggregated_data = {"channelEventsByTag": {channel_tag: [] for channel_tag in CHANNELS_CONFIG.keys()}}
    processed_event_ids = set()

    print(f"Starting EPG fetch for {TOTAL_DAYS_TO_FETCH} days in {num_iterations} chunks...")

    for n in range(num_iterations):
        start_dt = now + timedelta(hours=n * chunk_duration_hours)
        end_dt = now + timedelta(hours=(n + 1) * chunk_duration_hours)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        grid_url = f'{grid_base_url}?startDate={start_ms}&endDate={end_ms}' #&regionId=20480'

        print(f"\nFetching grid chunk {n + 1}/{num_iterations}...")

        try:
            response = requests.get(grid_url, headers=headers)
            response.raise_for_status()
            chunk_data = response.json()

            if "channelEventsByTag" in chunk_data:
                for channel_tag, events in chunk_data["channelEventsByTag"].items():
                    # Filter based on the keys in the new CHANNELS_CONFIG dictionary
                    if channel_tag in CHANNELS_CONFIG:
                        for event_summary in events:
                            event_id = event_summary.get("eventId")
                            if event_id and event_id not in processed_event_ids:
                                print(f"  Fetching details for event ID: {event_id} ({event_summary.get('programTitle', '')})")

                                event_detail_url = f"{event_base_url}{event_id}?movieHeight=720&tvShowHeight=720&regionId=20480"
                                try:
                                    event_response = requests.get(event_detail_url, headers=headers)
                                    event_response.raise_for_status()
                                    event_detail_json = event_response.json()

                                    if "event" in event_detail_json:
                                        aggregated_data["channelEventsByTag"][channel_tag].append(event_detail_json["event"])
                                        processed_event_ids.add(event_id)

                                    time.sleep(0.1)

                                except requests.exceptions.RequestException as e:
                                    print(f"    - Could not fetch details for event {event_id}. Using summary. Error: {e}")
                                    aggregated_data["channelEventsByTag"][channel_tag].append(event_summary)
                                    processed_event_ids.add(event_id)

        except requests.exceptions.RequestException as e:
            print(f"    Error fetching grid data for chunk {n + 1}: {e}")
        except json.JSONDecodeError:
            print(f"    Error decoding JSON for grid chunk {n + 1}. Skipping.")

    return aggregated_data


def convert_to_xmltv(json_data):
    """
    Converts the aggregated and detailed JSON data into a standardized XMLTV format.
    """
    if not json_data or not json_data.get("channelEventsByTag"):
        print("Error: No valid JSON data to convert.")
        return None

    local_tz = pytz.timezone('Australia/Sydney')
    root = ET.Element("tv", {"generator-info-name": "Foxtel EPG Scraper"})

    print("\nGenerating XMLTV file...")
    # --- Create Channel Elements using the new CHANNELS_CONFIG ---
    for channel_tag, channel_info in CHANNELS_CONFIG.items():
        xml_channel_id = f"{channel_info['id_num']}.{channel_tag}"
        channel_el = ET.SubElement(root, "channel", {"id": xml_channel_id})
        ET.SubElement(channel_el, "display-name").text = channel_info['display_name']
        ET.SubElement(channel_el, "icon", {"src": ICON_MAP.get(channel_tag, DEFAULT_ICON)})

    # --- Create Programme Elements ---
    for channel_tag, events in json_data["channelEventsByTag"].items():
        print(f"  Processing {len(events)} events for channel: {channel_tag}")

        # Get the config for the current channel to build the correct ID
        channel_info = CHANNELS_CONFIG.get(channel_tag)
        if not channel_info:
            continue # Skip if the channel is not in our config

        xml_channel_id = f"{channel_info['id_num']}.{channel_tag}"

        for event in events:
            try:
                start_ts = event['scheduledDate'] / 1000
                duration_minutes = event.get('duration', 0)

                start_dt_utc = datetime.fromtimestamp(start_ts, tz=timezone.utc)
                end_dt_utc = start_dt_utc + timedelta(minutes=duration_minutes)

                start_dt_local = start_dt_utc.astimezone(local_tz)
                end_dt_local = end_dt_utc.astimezone(local_tz)

                start_time_str = start_dt_local.strftime('%Y%m%d%H%M%S %z')
                end_time_str = end_dt_local.strftime('%Y%m%d%H%M%S %z')

                programme_el = ET.SubElement(root, "programme", {
                    "start": start_time_str,
                    "stop": end_time_str,
                    "channel": xml_channel_id  # Use the correctly formatted ID
                })

                ET.SubElement(programme_el, "title", {"lang": "en"}).text = event.get('programTitle', 'No Title')

                if event.get('episodeTitle'):
                    ET.SubElement(programme_el, "sub-title", {"lang": "en"}).text = event.get('episodeTitle')

                description = event.get('mergedSynopsis', event.get('shortSynopsis', ''))
                ET.SubElement(programme_el, "desc", {"lang": "en"}).text = description

                if event.get('imageUrl'):
                    ET.SubElement(programme_el, "icon", {"src": event['imageUrl']})

                s_num = event.get('seriesNumber')
                e_num = event.get('episodeNumber')
                if s_num and e_num:
                    ET.SubElement(programme_el, "episode-num", {"system": "xmltv_ns"}).text = f"{int(s_num) - 1}.{int(e_num) - 1}."

                rating = event.get('parentalRating')
                if rating and rating != "NC":
                    rating_el = ET.SubElement(programme_el, "rating")
                    ET.SubElement(rating_el, "value").text = rating

            except KeyError as e:
                print(f"    Skipping event due to missing key: {e}")
            except Exception as e:
                print(f"    An unexpected error occurred while processing an event: {e}")

    ET.indent(root, space="  ", level=0)
    xml_string = ET.tostring(root, encoding="UTF-8", xml_declaration=True).decode('utf-8')
    return xml_string


# --- Main Execution ---
if __name__ == "__main__":
    epg_json = fetch_epg_data()

    if epg_json and any(epg_json["channelEventsByTag"].values()):
        xmltv_output = convert_to_xmltv(epg_json)

        if xmltv_output:
            output_filename = "guide.xml"
            try:
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(xmltv_output)
                print(f"\n✅ XMLTV data successfully generated and saved to {output_filename}")
            except IOError as e:
                print(f"\n❌ Error saving file: {e}")
    else:
        print("\n❌ No programme data was fetched. The XML file was not generated.")
