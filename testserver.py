#!/usr/bin/env python

import atexit
import os
import re
import signal
import ssl
import shutil
import subprocess
import tempfile
import time
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
        if url.startswith('https://localhost'):
            if get_http_status._shouldWarnAboutCertValidation:
                get_http_status._shouldWarnAboutCertValidation = False
                print('Warning: Disabling certificate validation for testing')
            context = ssl._create_unverified_context()
            return urlopen(req, context=context).getcode()
        return urlopen(req).getcode()
    except HTTPError as e:
        return e.code

get_http_status._shouldWarnAboutCertValidation = True


def good_headers():
    '''A dictionary of expected good headers.'''
    return {
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.94 Safari/537.36',  # NOQA
        'deduplication-id': '0123456789',
        'extension-version': '0',
    }


class LocalServer:
    instance = None
    # Let's hard-code them for now.
    http_port = 8088
    https_port = 8443

    server_proc = None
    nginx_root_path = ''
    nginx_prefix_path = ''
    nginx_log_path = ''

    @staticmethod
    def Get():
        if not LocalServer.instance:
            LocalServer.instance = LocalServer()
            LocalServer.instance.start_server()
        return LocalServer.instance

    def _create_nginx_root_content(self):
        '''
        Create a temporary directory containing the the Nginx server's config.
        '''
        def src_path(x): return os.path.join(os.path.dirname(__file__), x)

        with open(src_path('nl.robwu.pdfjs.conf')) as f:
            server_conf = f.read()

        for count, needle, replacement in [
            # Listen on localhost only.
            [0, '(?= listen )', ' #'],
            [1, '(?=# listen.*80;)', 'listen %d; ' % self.http_port],
            [1, '(?=# listen.*443 ssl;)', 'listen %d ssl; ' % self.https_port],

            # Self-signed test certificates, e.g. via
            # openssl req -x509 -newkey rsa:2048 -keyout localhost.key -out localhost.crt -nodes -sha256 -subj '/CN=localhost'  # NOQA
            [1, '( ssl_certificate) .+;', r'\1 localhost.crt;'],
            [1, '( ssl_certificate_key) .+;', r'\1 localhost.key;'],

            # Write to a temporary access log instead of a system destination.
            [1, '( access_log) /[^ ]+', r'\1 localhost.log'],

            # Without this, it takes 5 seconds before the logs are flushed.
            # Also, when worker processes are used, this also slows down
            # termination by 5s (because workers wait until the sockets are
            # closed upon a graceful shutdown).
            [1, 'server {', 'server { lingering_close off;'],
        ]:
            rneedle = re.compile(needle)
            found = rneedle.findall(server_conf)
            if not found:
                raise ValueError('Not found in source: %s' % needle)
            if count and len(found) < count:
                raise ValueError('Expected %d, but got %d for: %s' % (
                    count, len(found), needle))
            server_conf = re.sub(
                    rneedle, replacement, server_conf, count=count)

        # Generation succeeded, create files.

        nginx_root = tempfile.mkdtemp(prefix='nginx_test_server')
        with open(os.path.join(nginx_root, 'nl.robwu.pdfjs.conf'), 'w') as f:
            f.write(server_conf)

        for filename in [
            'nginx.conf',
            # For testing, these are actually self-signed certificates.
            'localhost.crt',
            'localhost.key',
        ]:
            shutil.copyfile(src_path(filename),
                            os.path.join(nginx_root, filename))

        prefix_path = os.path.join(nginx_root, 'prefix')
        os.mkdir(prefix_path)
        # Required by nginx, "temp" as specific in nginx.conf
        os.mkdir(os.path.join(prefix_path, 'temp'))

        self.nginx_root_path = nginx_root
        self.nginx_prefix_path = prefix_path

    def start_server(self):
        '''
        Start a Nginx server at the given ports.
        '''

        if not self.nginx_root_path:
            self._create_nginx_root_content()

        self.nginx_log_path = '%s/localhost.log' % self.nginx_prefix_path

        print('Starting nginx server at %s' % self.nginx_root_path)
        self.server_proc = subprocess.Popen([
            'nginx',
            '-p', self.nginx_prefix_path,
            '-c', os.path.join(self.nginx_root_path, 'nginx.conf'),
            '-g', 'daemon off; master_process off;',
        ])

        atexit.register(self.stop_server)

        # Wait until the server has started (at most a few seconds)
        for i in range(0, 10):
            try:
                get_http_status('http://localhost:%d' % self.http_port)
                return  # Request succeeded, server started.
            except URLError:
                time.sleep(0.2)

    def stop_server(self):
        self.server_proc.send_signal(signal.SIGQUIT)
        self.server_proc.wait()
        self.server_proc = None

    def get_http_base_url(self):
        return 'http://localhost:%d' % self.http_port

    def get_https_base_url(self):
        return 'https://localhost:%d' % self.https_port

    def get_log_content(self):
        # Assume that the logs have been written.
        # We have set lingering_close to "off", and from Python's side (urllib)
        # the request has ended, so the log should immediately be flushed.
        with open(self.nginx_log_path, 'r') as f:
            return f.read()


class TestHttpBase(object):
    '''
    These tests check whether the response from the logging server is OK.
    If the response is 204, it's assumed that an entry is written to the log,
    but the tests do NOT check whether the log is actually written.
    '''

    @classmethod
    def setUpClass(cls):
        cls.base_url = cls.get_base_url()
        # Check whether we can connect before running all other tests.
        get_http_status(cls.base_url)

    def assertStatus(self, expected_status, path, **kwargs):
        http_method = 'POST' if 'data' in kwargs else 'GET'
        status = get_http_status(self.base_url + path, **kwargs)
        msg = 'Expected %d but got %d for %s %s' % (
                expected_status, status, http_method, path)
        self.assertEqual(expected_status, status, msg)

    def test_non_existing_404(self):
        self.assertStatus(404, '/')
        self.assertStatus(404, '/favicon.ico')
        # Actually, robots.txt is supported to avoid getting crawled.
        self.assertStatus(200, '/robots.txt')

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

    def test_logging_valid_deduplication_id(self):
        headers = good_headers()
        headers['deduplication-id'] = '0123abcdef'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

    def test_logging_invalid_deduplication_id(self):
        # Note that the last character in Deduplication-Id is an uppercase 'F'.
        headers = good_headers()
        headers['deduplication-id'] = '012345678F'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        headers = good_headers()
        headers['deduplication-id'] = '012345678g'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Too short
        headers = good_headers()
        headers['deduplication-id'] = '012345678'
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        # Too long
        headers = good_headers()
        headers['deduplication-id'] = '0123456789a'
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


class TestLocalBase(object):
    '''
    Tests specific to a local Nginx instance.
    '''
    def test_did_write_log(self):
        old_log = LocalServer.Get().get_log_content()

        headers = good_headers()
        headers['extension-version'] = '1337'
        self.assertStatus(204, '/logpdfjs', data=b'', headers=headers)

        new_log = LocalServer.Get().get_log_content()

        new_log = new_log[len(old_log):]
        self.assertNotEqual(new_log, '', 'Expected a new log entry.')
        self.assertEqual(new_log, '0123456789 1337 "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.94 Safari/537.36"\n')  # NOQA

    def test_did_not_write_log(self):
        old_log = LocalServer.Get().get_log_content()

        headers = good_headers()
        headers['extension-version'] = ''
        self.assertStatus(400, '/logpdfjs', data=b'', headers=headers)

        new_log = LocalServer.Get().get_log_content()

        new_log = new_log[len(old_log):]
        self.assertEqual(new_log, '', 'Expected a new log entry.')


class TestHttp(TestHttpBase, TestLocalBase, unittest.TestCase):
    @staticmethod
    def get_base_url():
        return LocalServer.Get().get_http_base_url()


class TestHttps(TestHttpBase, TestLocalBase, unittest.TestCase):
    @staticmethod
    def get_base_url():
        return LocalServer.Get().get_https_base_url()


class TestProd(TestHttpBase, unittest.TestCase):
    @staticmethod
    def get_base_url():
        return 'https://pdfjs.robwu.nl'

if __name__ == '__main__':
    unittest.main()
