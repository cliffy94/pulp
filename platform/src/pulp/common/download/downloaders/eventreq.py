# -*- coding: utf-8 -*-
#
# Copyright © 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the License
# (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied, including the
# implied warranties of MERCHANTABILITY, NON-INFRINGEMENT, or FITNESS FOR A
# PARTICULAR PURPOSE.
# You should have received a copy of GPLv2 along with this software;
# if not, see http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt

# first, so that all subsequently imported modules are the monkey patched versions
import eventlet
eventlet.monkey_patch()

import datetime
import httplib
import urllib
from logging import getLogger

import requests

from pulp.common import dateutils
from pulp.common.download.downloaders.base import PulpDownloader
from pulp.common.download.report import DownloadReport, DOWNLOAD_SUCCEEDED

# -- constants -----------------------------------------------------------------

_LOG = getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 5
DEFAULT_BUFFER_SIZE = 8192
DEFAULT_PROGRESS_INTERVAL = 5

# -- exception classes ---------------------------------------------------------

class DownloadCancelled(Exception):
    def __init__(self, url):
        super(DownloadCancelled, self).__init__(url)
    def __str__(self):
        return 'Download of %s was cancelled' % self.args[0]

class DownloadFailed(Exception):
    def __init__(self, url, code, msg=None):
        super(DownloadFailed, self).__init__(url, code, msg)
    def __str__(self):
        return 'Download of %s failed with code %d: %s' % tuple(a for a in self.args)

# -- downloader class ----------------------------------------------------------

class HTTPEventletRequestsDownloader(PulpDownloader):
    """
    Downloader class that uses the third party Eventlets with Requests to handle
    HTTP, HTTPS and proxied download requests by the server.
    """

    @property
    def buffer_size(self):
        return self.config.buffer_size or DEFAULT_BUFFER_SIZE

    @property
    def max_concurrent(self):
        return self.config.max_concurrent or DEFAULT_MAX_CONCURRENT

    @property
    def progress_interval(self):
        # cache the progress interval for better performance
        if not hasattr(self, '_progress_interval'):
            seconds = self.config.progress_interval or DEFAULT_PROGRESS_INTERVAL
            self._progress_interval = datetime.timedelta(seconds=seconds)
        return self._progress_interval

    def download(self, request_list):

        pool = eventlet.GreenPool(size=self.max_concurrent)
        session = build_session(self.config)

        def _session_generator():
            yield session

        for report in pool.imap(self._fetch, request_list, _session_generator()):
            if report.state is DOWNLOAD_SUCCEEDED:
                self.fire_download_succeeded(report)
            else: # DOWNLOAD_FAILED
                self.fire_download_failed(report)

    def _fetch(self, request, session):
        report = DownloadReport.from_download_request(request)
        report.download_started()
        self.fire_download_started(report)

        last_update_time = report.start_time

        try:
            if self.is_canceled:
                raise DownloadCancelled(request.url)

            response = session.get(request.url)

            if response.status_code != httplib.OK:
                raise DownloadFailed(request.url, response.status_code, response.reason)

            file_handle = request.initialize_file_handle()

            for chunk in response.iter_content(self.buffer_size):

                if self.is_canceled:
                    raise DownloadCancelled(request.url)

                file_handle.write(chunk)
                report.bytes_downloaded += len(chunk)

                last_update_time = self._interval_progress_report(last_update_time, report)

        except DownloadCancelled, e:
            _LOG.debug(str(e))
            report.download_canceled()

        except DownloadFailed, e:
            _LOG.error(str(e))
            report.error_report['response_code'] = e.args[1]
            report.error_report['response_msg'] = e.args[2]
            report.download_failed()

        except Exception, e:
            _LOG.exception(e)
            report.download_failed()

        else:
            report.download_succeeded()

        finally:
            request.finalize_file_handle()

        return report

    def _interval_progress_report(self, last_update_time, report):
        now = datetime.datetime.now(tz=dateutils.utc_tz())

        if now - last_update_time < self.progress_interval:
            return last_update_time

        self.fire_download_progress(report)
        return now

# -- requests utilities --------------------------------------------------------

def build_session(config):
    session = requests.Session()
    session.stream = True
    _add_basic_auth(session, config)
    _add_ssl(session, config)
    _add_proxy(session, config)
    return session


def _add_basic_auth(session, config):
    if None in (config.basic_auth_username, config.basic_auth_password):
        return
    session.auth = (config.basic_auth_username, config.basic_auth_password)


def _add_ssl(session, config):
    # NOTE using this logic automatically turns on ssl verification if a ca
    # certificate is provided, ignoring the boolean flag, which makes sense
    session.verify = config.ssl_ca_cert_path or config.ssl_validation

    client_cert_tuple = (config.ssl_client_cert_path, config.ssl_client_key_path)
    if None not in client_cert_tuple:
        session.cert = client_cert_tuple


def _add_proxy(session, config):
    if None in (config.proxy_url, config.proxy_port):
        return

    protocol, host = urllib.splittype(config.proxy_url)
    url = ':'.join((host, str(config.proxy_port)))

    if config.proxy_username is not None:
        password_part = config.get('proxy_password', '') and ':%s' % config.proxy_password
        auth = config.proxy_username + password_part
        url = '@'.join((auth, url))

    session.proxies[protocol] = url

