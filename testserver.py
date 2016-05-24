#!/usr/bin/env python

import re
import unittest

try:
    # Py3
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
except ImportError:
    # Py2
    from urllib2 import urlopen, HTTPError, Request, URLError


def get_http_status(url, **kwargs):
    req = Request(url,
                  data=kwargs.get('data', None),
                  headers=kwargs.get('headers', {}))
    try:
        return urlopen(req).getcode()
    except HTTPError as e:
        return e.code


def good_headers():
    '''A dictionary of expected good headers.'''
    return {
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.94 Safari/537.36',  # NOQA
        'deduplication-id': '0123456789abcdef0123456789abcdef',
        'extension-version': '0',
    }


class PdfJsLogTest(unittest.TestCase):
    '''
    These tests check whether the response from the logging server is OK.
    If the response is 204, it's assumed that an entry is written to the log,
    but the tests do NOT check whether the log is actually written.
    '''

    @classmethod
    def setUpClass(cls):
        cls.base_url = 'http://localhost:8080'
        cls.assertCanConnect()

    @classmethod
    def assertCanConnect(cls):
        try:
            get_http_status(cls.base_url)
        except URLError:
            print('##########################################################')
            print('### Cannot connect to server. Please start it using')
            print('# nginx -p prefix -c $PWD/nl.robwu.pdfjs.conf')
            print('### After changing the config, you can reapply it using')
            print('# nginx -p prefix -c $PWD/nl.robwu.pdfjs.conf -s reload')
            print('### And if you are done, quit the server using')
            print('# nginx -p prefix -c $PWD/nl.robwu.pdfjs.conf -s quit')
            print('##########################################################')
            raise

    def assertStatus(self, expected_status, path, **kwargs):
        http_method = 'POST' if 'data' in kwargs else 'GET'
        status = get_http_status(self.base_url + path, **kwargs)
        msg = 'Expected %d but got %d for %s %s' % (
                expected_status, status, http_method, path)
        self.assertEqual(expected_status, status, msg)

    def test_non_existing_404(self):
        self.assertStatus(404, '/')
        self.assertStatus(404, '/favicon.ico')
        self.assertStatus(404, '/robots.txt')

        self.assertStatus(404, '/', data=b'')

    def test_logging_invalid_method(self):
        self.assertStatus(405, '/logpdfjs')

    def test_logging_invalid_body(self):
        # Nginx doesn't allow us to disable the body, so the config accepts
        # length 1. Requests with bodies of size 2 should be rejected though.
        self.assertStatus(413, '/logpdfjs', data=b'12')

    def test_logging_valid_headers(self):
        self.assertStatus(204, '/logpdfjs', data=b'', headers=good_headers())

    def test_logging_invalid_headers(self):
        self.assertStatus(400, '/logpdfjs', data=b'', headers={})

        headers = good_headers()
        del headers['deduplication-id']
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Can't test a missing User-Agent header because urllib always adds it.
        # Let's assume that Nginx doesn't blow up when it is missing...

        headers = good_headers()
        del headers['extension-version']
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

    def test_logging_invalid_deduplication_id(self):
        # Note that the last character in Deduplication-Id is an uppercase 'F'.
        headers = good_headers()
        headers['deduplication-id'] = '0123456789abcdef0123456789abcdeF'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Too short
        headers = good_headers()
        headers['deduplication-id'] = '0123456789abcdef0123456789abcde'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Too long
        headers = good_headers()
        headers['deduplication-id'] = '0123456789abcdef0123456789abcdef0'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

    def test_logging_valid_user_agent(self):
        # Minimal allowed
        headers = good_headers()
        headers['user-agent'] = 'a'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

        # Maximum allowed.
        headers = good_headers()
        headers['user-agent'] = 'a' * 1000
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

    def test_logging_invalid_user_agent(self):
        # Too short
        headers = good_headers()
        headers['user-agent'] = ''
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Too long
        headers = good_headers()
        headers['user-agent'] = 'a' * 1001
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['user-agent'] = 'x\x00'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

    def test_logging_valid_extension_version(self):
        headers = good_headers()
        headers['extension-version'] = '0'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '0.0.0.0'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '65535.65535.65535.65535'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

    def test_logging_invalid_extension_version(self):
        headers = good_headers()
        headers['extension-version'] = ''
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '.'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '0.'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '.0'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['extension-version'] = '65536'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

    def test_extension_version_pattern(self):
        # Copy-paste of the numeric regex in the nginx config.
        regex = '^([0-5]?[0-9]{1,4}|6([0-4][0-9]{3}|5([0-4][0-9]{2}|5([0-2][0-9]|3[0-5]))))$'  # NOQA
        pattern = re.compile(regex, re.DOTALL)
        for i in range(0, 0xFFFF + 1):
            self.assertTrue(re.match(pattern, str(i)),
                            '%d should match the version pattern!' % i)

        self.assertFalse(re.match(pattern, str(0xFFFF + 1)),
                         '0xFFFF+1 should not match the version pattern!')


if __name__ == '__main__':
    unittest.main()
