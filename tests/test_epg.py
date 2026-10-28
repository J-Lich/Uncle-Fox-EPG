import contextlib
import io
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import requests

import epg_runtime as runtime
import fox_epg_scraper as fox
import kayo_epg_scraper as kayo


def response(data=None, status=200):
    result = requests.Response()
    result.status_code = status
    result.url = 'https://example.test/epg'
    result._content = b'{}'
    result.json = Mock(return_value=data)
    return result


def event(number):
    return {'eventId': str(number), 'programTitle': 'Test sport',
            'scheduledDate': 1793152800000, 'duration': 60}


class HttpTests(unittest.TestCase):
    @patch('epg_runtime.time.sleep')
    def test_timeout_retries_are_bounded(self, sleep):
        client = runtime.HttpClient()
        with patch.object(client.session, 'get', side_effect=requests.ReadTimeout('stalled')) as get:
            with self.assertRaises(requests.ReadTimeout):
                client.get('https://example.test/epg', headers={})
            self.assertEqual(get.call_count, 2)
            self.assertEqual(get.call_args.kwargs['timeout'], (5, 20))
        client.close()

    @patch('epg_runtime.time.sleep')
    def test_transient_error_recovers(self, sleep):
        client = runtime.HttpClient()
        with patch.object(client.session, 'get', side_effect=[response(status=503), response()]) as get:
            self.assertEqual(client.get('https://example.test/epg', headers={}).status_code, 200)
            self.assertEqual(get.call_count, 2)
        client.close()

    def test_permanent_error_is_not_retried(self):
        client = runtime.HttpClient()
        with patch.object(client.session, 'get', return_value=response(status=403)) as get:
            with self.assertRaises(requests.HTTPError):
                client.get('https://example.test/epg', headers={})
            self.assertEqual(get.call_count, 1)
        client.close()


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def test_fox_fetches_thumbnail_once_and_deduplicates_grid_overlap(self):
        client = Mock()
        def get(url, **kwargs):
            if '/grid/' in url:
                return response({'channelEventsByTag': {'FS1': [event(1)]}})
            return response({'event': event(1)})
        client.get.side_effect = get
        with patch.object(fox, 'fetch_thumbnail_image', return_value='https://example.test/image') as image:
            data = fox.fetch_epg_data(days=1, client=client)
            image.assert_called_once_with('1', client)
        self.assertEqual(len(data['channelEventsByTag']['FS1']), 1)
        self.assertEqual(len(ET.fromstring(fox.convert_to_xmltv(data)).findall('programme')), 1)

    def test_fox_optional_failures_stop_and_keep_grid_events(self):
        client = Mock()
        def get(url, **kwargs):
            if '/grid/' in url:
                return response({'channelEventsByTag': {'FS1': [event(n) for n in range(5)]}})
            raise requests.ReadTimeout('stalled')
        client.get.side_effect = get
        with patch.object(fox, 'fetch_thumbnail_image', return_value=None) as image:
            data = fox.fetch_epg_data(days=1, client=client)
        self.assertEqual(image.call_count, 3)
        self.assertEqual(client.get.call_count, 4 + 3)
        self.assertEqual(len(data['channelEventsByTag']['FS1']), 5)

    def test_fox_existing_api_image_skips_thumbnail(self):
        client = Mock()
        client.get.side_effect = lambda url, **kw: response(
            {'channelEventsByTag': {'FS1': [event(1)]}} if '/grid/' in url
            else {'event': dict(event(1), imageUrl='https://example.test/image')})
        with patch.object(fox, 'fetch_thumbnail_image') as image:
            fox.fetch_epg_data(days=1, client=client)
        image.assert_not_called()

    def test_failed_grid_does_not_return_partial_data(self):
        client = Mock()
        client.get.side_effect = [response({'channelEventsByTag': {'FS1': []}}), requests.ReadTimeout('stalled')]
        with self.assertRaises(RuntimeError):
            fox.fetch_epg_data(days=2, client=client)


class OutputTests(unittest.TestCase):
    def test_empty_output_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'guide.xml'
            path.write_text('existing guide')
            with self.assertRaises(ValueError):
                runtime.write_guide('<tv><channel id="a"/></tv>', path)
            self.assertEqual(path.read_text(), 'existing guide')

    def test_replace_failure_preserves_existing_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'guide.xml'
            path.write_text('existing guide')
            with patch('epg_runtime.os.replace', side_effect=OSError('disk error')), self.assertRaises(OSError):
                runtime.write_guide('<tv><programme/></tv>', path)
            self.assertEqual(path.read_text(), 'existing guide')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_success_replaces_existing_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'guide.xml'
            path.write_text('existing guide')
            with patch('sys.argv', ['scraper']):
                status = runtime.run_generator(Mock(return_value=[]),
                                               Mock(return_value='<tv><programme/></tv>'),
                                               days=1, output=str(path), max_seconds=10)
            self.assertEqual(status, 0)
            self.assertEqual(len(ET.parse(path).findall('programme')), 1)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_failure_returns_nonzero_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'guide.xml'
            path.write_text('existing guide')
            with patch('sys.argv', ['scraper']):
                status = runtime.run_generator(Mock(side_effect=RuntimeError('upstream failed')), Mock(),
                                               days=1, output=str(path), max_seconds=10)
            self.assertEqual(status, 1)
            self.assertEqual(path.read_text(), 'existing guide')

    @unittest.skipUnless(hasattr(signal, 'SIGALRM'), 'POSIX run deadline')
    def test_run_deadline_interrupts_a_stalled_operation(self):
        with patch('sys.argv', ['scraper']):
            start = time.monotonic()
            status = runtime.run_generator(lambda **kwargs: time.sleep(10), Mock(),
                                           days=1, output='unused.xml', max_seconds=1)
        self.assertEqual(status, 1)
        self.assertLess(time.monotonic() - start, 3)


if __name__ == '__main__':
    unittest.main()
