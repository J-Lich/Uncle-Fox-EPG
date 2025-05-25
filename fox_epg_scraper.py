import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta # Import timedelta
import requests

# --- Define the Icon Mapping ---
ICON_MAP = {
    "FOX Cricket": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Cricket.png",
    "FOX Footy": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Footy.png",
    "FOX League": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20League.png",
    "FOX Sports 503": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20503.png",
    "FOX Sports 505": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20505.png",
    "FOX Sports 506": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20506.png",
    "FOX Sports More": "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports%20More.png",
}
DEFAULT_ICON = "https://raw.githubusercontent.com/J-Lich/Uncle-Fox-EPG/main/icons/FOX%20Sports.png"
# --- End Icon Mapping ---

def fetch_tv_guide_data(start_date, end_date, channel_id):
    """
    Fetches TV guide data and extracts JSON using a flexible approach.
    """
    url = f'https://tvguide.foxsports.com.au/granite-api/programmes.json?from={start_date}&to={end_date}&channel={channel_id}&callback=handleTvGuide'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://tvguide.foxsports.com.au/'
    }

    try:
        print(f"Fetching data from: {url}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        jsonp_text = response.text.strip()

        try:
            start_index = jsonp_text.index("{")
            end_index = jsonp_text.rindex("}") + 1
            json_string = jsonp_text[start_index:end_index]
            print("Successfully extracted potential JSON. Attempting to parse...")
            return json.loads(json_string)

        except ValueError:
            print("Error: Could not find '{' or '}' in the response.")
            return None
        except json.JSONDecodeError as e:
            print(f"Error parsing extracted JSON: {e}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def convert_to_xmltv(json_data):
    """
    Converts JSON data to an XMLTV file with dynamic icons.
    """
    if not json_data or "channel-programme" not in json_data:
        print("Error: Invalid JSON data format.")
        return None

    root = ET.Element("tv")

    channels = {}
    for programme_data in json_data["channel-programme"]:
        channel_name = programme_data["channelName"]
        channel_id_num = str(programme_data["channelId"])
        new_channel_id = channel_name.replace(" ", ".") + "." + channel_id_num

        if new_channel_id not in channels:
            channels[new_channel_id] = channel_name
            channel_el = ET.SubElement(root, "channel", {"id": new_channel_id})
            ET.SubElement(channel_el, "display-name").text = channel_name
            icon_url = ICON_MAP.get(channel_name, DEFAULT_ICON)
            ET.SubElement(channel_el, "icon", {"src": icon_url})

    for programme_data in json_data["channel-programme"]:
        try:
            start_dt = datetime.fromisoformat(programme_data["startTime"])
            end_dt = datetime.fromisoformat(programme_data["endTime"])

            start_time = start_dt.strftime("%Y%m%d%H%M%S %z")
            end_time = end_dt.strftime("%Y%m%d%H%M%S %z")

            title_parts = []
            if programme_data.get("live"):
                title_parts.append("LIVE:")
            title_parts.append(programme_data.get("programmeTitle", "N/A"))
            sub_title_text = programme_data.get("title")
            if sub_title_text:
                title_parts.append(sub_title_text)
            title_parts.append(start_dt.strftime("%Y"))
            new_title = " ".join(title_parts)

            prog_channel_name = programme_data["channelName"]
            prog_channel_id_num = str(programme_data["channelId"])
            prog_channel_id = prog_channel_name.replace(" ", ".") + "." + prog_channel_id_num

            programme_el = ET.SubElement(root, "programme", {
                "start": start_time,
                "stop": end_time,
                "channel": prog_channel_id
            })

            ET.SubElement(programme_el, "title", {"lang": "en"}).text = new_title
            ET.SubElement(programme_el, "desc", {"lang": "en"}).text = programme_data.get("synopsis", "")
            ET.SubElement(programme_el, "date").text = start_dt.strftime("%Y")
            icon_url = ICON_MAP.get(prog_channel_name, DEFAULT_ICON)
            ET.SubElement(programme_el, "icon", {"src": icon_url})
            ET.SubElement(programme_el, "category", {"lang": "en"}).text = programme_data.get("genreTitle", "")
            if programme_data.get("parentGenreTitle"):
                 ET.SubElement(programme_el, "category", {"lang": "en"}).text = programme_data.get("parentGenreTitle")

        except Exception as e:
            print(f"Error processing programme: {programme_data.get('id')}, Error: {e}")
    
    ET.indent(root, space="  ", level=0)
    xml_string = ET.tostring(root, encoding="UTF-8", xml_declaration=True).decode('utf-8')
    return xml_string


# --- Main part of the script ---
# *** DYNAMIC DATES ***
start_date_dt = datetime.now() 
# Fetch for the next 30 days (adjust as needed)
end_date_dt = start_date_dt + timedelta(days=30) 

start_date = start_date_dt.strftime("%Y-%m-%d")
end_date = end_date_dt.strftime("%Y-%m-%d")

print(f"Running EPG update for dates: {start_date} to {end_date}")

# *** Make sure this list contains all channel IDs you need ***
channel_ids_to_fetch = [10, 13, 3, 12, 14, 2, 11] 

all_programmes = []

for ch_id in channel_ids_to_fetch:
    print(f"\nFetching data for channel ID: {ch_id}")
    tv_guide_json_single = fetch_tv_guide_data(start_date, end_date, ch_id)
    if tv_guide_json_single and "channel-programme" in tv_guide_json_single:
         all_programmes.extend(tv_guide_json_single["channel-programme"])
    else:
        print(f"No data or error fetching for channel ID: {ch_id}")

if all_programmes:
    tv_guide_json = {"channel-programme": all_programmes}
    xmltv_output = convert_to_xmltv(tv_guide_json)

    if xmltv_output:
        output_filename = "guide.xml" # This is the file we will commit
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(xmltv_output)
            print(f"\nXMLTV data successfully saved to {output_filename}")
        except IOError as e:
            print(f"Error saving file: {e}")
else:
    print("\nNo programme data was fetched.")
