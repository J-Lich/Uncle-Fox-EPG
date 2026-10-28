"""Bounded HTTP requests, diagnostics and safe output for the EPG generators."""
import argparse
import logging
import os
from pathlib import Path
import signal
import tempfile
import time
import xml.etree.ElementTree as ET

import requests

LOG = logging.getLogger(__name__)


class RunDeadlineExceeded(BaseException):
    """Escape per-event exception handlers when the whole run expires."""


class HttpClient:
    def __init__(self):
        self.session = requests.Session()
        self.requests = 0
        self.started = time.monotonic()

    def get(self, url, *, headers, timeout=(5, 20), attempts=2):
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            self.requests += 1
            LOG.info('GET attempt=%d/%d timeout=%s %s', attempt, attempts, timeout, url)
            try:
                response = self.session.get(url, headers=headers, timeout=timeout)
                LOG.info('HTTP %d elapsed=%.2fs bytes=%d type=%s',
                         response.status_code, time.monotonic() - started,
                         len(response.content), response.headers.get('Content-Type', '?'))
                if response.status_code >= 400:
                    LOG.debug('Error response: %s', response.text[:300].replace('\n', ' '))
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                LOG.warning('%s after %.2fs: %s', type(exc).__name__, time.monotonic() - started, exc)
                status = exc.response.status_code if exc.response is not None else None
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status in (429, 500, 502, 503, 504)
                if attempt == attempts or not retryable:
                    raise
                time.sleep(attempt)

    def close(self):
        LOG.info('Run summary: requests=%d elapsed=%.2fs', self.requests, time.monotonic() - self.started)
        self.session.close()


def write_guide(xml, output):
    if not xml or not ET.fromstring(xml).findall('programme'):
        raise ValueError('No programmes generated; keeping the previous guide')
    output = Path(output)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix=output.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            handle.write(xml)
        os.replace(temporary, output)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    LOG.info('Saved %d programmes to %s', len(ET.fromstring(xml).findall('programme')), output)


def run_generator(fetch, convert, *, days, output, max_seconds, thumbnails=False):
    parser = argparse.ArgumentParser(description='Generate XMLTV with bounded requests and timing logs.')
    parser.add_argument('--days', type=int, default=days)
    parser.add_argument('--output', default=output)
    parser.add_argument('--max-seconds', type=int, default=max_seconds)
    parser.add_argument('--debug', action='store_true', help='Include HTTP error response previews')
    if thumbnails:
        parser.add_argument('--skip-thumbnails', action='store_true')
    args = parser.parse_args()
    if args.days < 1 or args.max_seconds < 1:
        parser.error('--days and --max-seconds must be positive')
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    client = HttpClient()
    def deadline(signum, frame):
        raise RunDeadlineExceeded(f'Run exceeded {args.max_seconds}s; keeping the previous guide')
    previous_handler = None
    if hasattr(signal, 'SIGALRM'):
        previous_handler = signal.signal(signal.SIGALRM, deadline)
        signal.alarm(args.max_seconds)
    try:
        kwargs = {'days': args.days, 'client': client}
        if thumbnails:
            kwargs['thumbnails'] = not args.skip_thumbnails
        data = fetch(**kwargs)
        write_guide(convert(data), args.output)
        return 0
    except (Exception, RunDeadlineExceeded) as exc:
        LOG.error('Generation failed: %s', exc, exc_info=args.debug)
        return 1
    finally:
        if previous_handler is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
        client.close()
