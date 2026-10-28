from datetime import date, datetime, timedelta
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

import requests
import kayo_epg_scraper as kayo

STARTUP = {'Region': {'isAllowed': True, 'Country': 'au'}, 'ServiceDictionary': {
    'EpgWithDateRange': {'Versions': {'v6': {'ServicePath': 'https://example.test/epg'}}},
    'img': {'Versions': {'v3': {'ServicePath': 'https://example.test/image'}}}}}


def tile(**overrides):
    data = {'AssetId': 'asset1', 'LinearProvider': 'fsa501', 'Title': 'Match & highlights',
            'Start': '2026-10-28T10:00:00Z', 'End': None, 'ExpirationDate': '2026-10-28T10:10:00Z',
            'Competition': {'Title': 'Cricket'}, 'Description': 'Live <sport>',
            'Image': {'Id': 'header_image'}, 'Type': 'UpComing'}
    return dict(data, **overrides)


def fake_client():
    client = Mock()
    def get(url, **kwargs):
        if url == kayo.STARTUP_URL:
            return Mock(json=Mock(return_value=STARTUP))
        params = parse_qs(urlsplit(url).query)
        return Mock(json=Mock(return_value={'Tiles': [tile()],
                    'StartDate': params['startDate'][0], 'EndDate': params['endDate'][0]}))
    client.get.side_effect = get
    return client


class KayoCurrentApiTests(unittest.TestCase):
    def test_fourteen_days_use_two_seven_day_requests(self):
        client = fake_client()
        data = kayo.fetch_epg_data(days=14, client=client)
        urls = [call.args[0] for call in client.get.call_args_list]
        self.assertEqual(urls[0], kayo.STARTUP_URL)
        windows = []
        for url in urls[1:]:
            p = parse_qs(urlsplit(url).query)
            first, last = date.fromisoformat(p['startDate'][0]), date.fromisoformat(p['endDate'][0])
            self.assertLessEqual((last-first).days, 6)
            windows.extend(first+timedelta(days=n) for n in range((last-first).days+1))
            self.assertEqual(p['brand'], ['kayo'])
            self.assertEqual(p['openBrowse'], ['true'])
        today = datetime.now(kayo.SYDNEY).date()
        self.assertEqual(windows, [today+timedelta(days=n) for n in range(14)])
        self.assertTrue(data[0]['image_url'].startswith('https://example.test/image/none/header_image/'))

    def test_windows_split_at_dst_offset_change(self):
        windows = list(kayo.date_windows(date(2026, 10, 3), 7))
        self.assertEqual(windows, [(date(2026, 10, 3), date(2026, 10, 4), 600),
                                  (date(2026, 10, 5), date(2026, 10, 9), 660)])

    def test_failed_second_window_does_not_publish_partial_fetch(self):
        client = fake_client()
        get = client.get.side_effect
        count = 0
        def fail_last(url, **kwargs):
            nonlocal count
            count += 1
            if count == 3:
                raise requests.ReadTimeout('stalled')
            return get(url, **kwargs)
        client.get.side_effect = fail_last
        with self.assertRaises(requests.ReadTimeout):
            kayo.fetch_epg_data(days=14, client=client)

    def test_wrong_range_or_schema_is_rejected(self):
        for data in [{'Tiles': []}, {'panels': []}]:
            client = Mock()
            client.get.side_effect = [Mock(json=Mock(return_value=STARTUP)), Mock(json=Mock(return_value=data))]
            with self.assertRaises(ValueError):
                kayo.fetch_epg_data(days=1, client=client)

    def test_disallowed_region_is_rejected(self):
        client = Mock()
        client.get.return_value.json.return_value = {'Region': {'Country': 'au', 'isAllowed': False}}
        with self.assertRaises(ValueError):
            kayo.fetch_epg_data(days=1, client=client)
        self.assertEqual(client.get.call_count, 1)

    def test_preserves_all_six_channel_ids(self):
        events = [tile(LinearProvider=provider) for provider in kayo.KAYO_CHANNEL_MAP]
        root = ET.fromstring(kayo.convert_to_xmltv(events))
        expected = {f"{info['id_num']}.{tag}" for tag, info in kayo.CHANNELS_CONFIG.items()}
        self.assertEqual({p.get('channel') for p in root.findall('programme')}, expected)
        self.assertEqual({c.get('id') for c in root.findall('channel')}, expected)

    def test_unknown_stop_is_omitted_not_asset_expiration(self):
        root = ET.fromstring(kayo.convert_to_xmltv([tile()]))
        programme = root.find('programme')
        self.assertNotIn('stop', programme.attrib)
        self.assertEqual(programme.get('start'), '20261028210000 +1100')
        self.assertEqual(programme.findtext('title'), 'Cricket: Match & highlights')
        self.assertEqual(programme.findtext('desc'), 'Live <sport>')

    def test_actual_end_is_used(self):
        root = ET.fromstring(kayo.convert_to_xmltv([tile(End='2026-10-28T12:30:00Z')]))
        self.assertEqual(root.find('programme').get('stop'), '20261028233000 +1100')

    def test_deduplication_keeps_repeated_broadcasts(self):
        root = ET.fromstring(kayo.convert_to_xmltv([tile(), tile(), tile(Start='2026-10-29T10:00:00Z')]))
        self.assertEqual(len(root.findall('programme')), 2)

    def test_unmapped_providers_are_not_assigned_by_sport(self):
        root = ET.fromstring(kayo.convert_to_xmltv([tile(LinearProvider='kayo')]))
        self.assertEqual(root.findall('programme'), [])

    def test_invalid_mapped_event_is_not_silently_dropped(self):
        for event in [tile(Start=None), tile(Start='2026-10-28T10:00:00'), tile(End='2026-10-28T09:00:00Z')]:
            with self.assertRaises((ValueError, TypeError)):
                kayo.convert_to_xmltv([event])


if __name__ == '__main__':
    unittest.main()
