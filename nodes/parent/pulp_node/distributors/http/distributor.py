# -*- coding: utf-8 -*-
#
# Copyright © 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from gettext import gettext as _
from logging import getLogger

from pulp.plugins.distributor import Distributor
from pulp.server.managers import factory
from pulp.server.config import config as pulp_conf

from pulp_node import link
from pulp_node import constants
from pulp_node.conduit import NodesConduit
from pulp_node.distributors.http.publisher import HttpPublisher
from pulp_node.manifest import Manifest


_LOG = getLogger(__name__)


# --- i18n ------------------------------------------------------------------------------

PROPERTY_MISSING = _('Missing required configuration property: %(p)s')
PROPERTY_INVALID = _('Property %(p)s must be: %(v)s')


# --- configuration ---------------------------------------------------------------------


# This should be in /etc/pulp
DEFAULT_CONFIGURATION = {
    constants.PROTOCOL_KEYWORD: 'https',
    'http': {
        'alias': [
            '/pulp/nodes/http/repos',
            '/var/www/pulp/nodes/http/repos'
        ]
    },
    'https': {
        'alias': [
            '/pulp/nodes/https/repos',
            '/var/www/pulp/nodes/https/repos'
        ],
        constants.SSL_KEYWORD: {
            constants.CLIENT_CERT_KEYWORD: {
                'local': '/etc/pki/pulp/nodes/local.crt',
                'child': '/etc/pki/pulp/nodes/parent/client.crt'
            }
        }
    }
}


# --- plugin loading --------------------------------------------------------------------


def entry_point():
    """
    Entry point that pulp platform uses to load the distributor.
    :return: distributor class and its configuration.
    :rtype:  Distributor, {}
    """
    return NodesHttpDistributor, DEFAULT_CONFIGURATION


# --- plugin ----------------------------------------------------------------------------


class NodesHttpDistributor(Distributor):
    """
    The (nodes) distributor
    """

    @classmethod
    def metadata(cls):
        return {
            'id' : constants.HTTP_DISTRIBUTOR,
            'display_name' : 'Pulp Nodes HTTP Distributor',
            'types' : ['node',]
        }

    def validate_config(self, repo, config, related_repos):
        """
        Layout:
          {
            protocol : (http|https|file),
            http : {
              alias : [url, directory]
            },
            https : {
              alias : [url, directory],
              ssl (optional) : {
                ca_cert : <path>,
                client_cert : <path>
                verify : <bool>
              }
            }
          }
        """
        key = constants.PROTOCOL_KEYWORD
        protocol = config.get(key)
        valid_protocols = ('http', 'https', 'file')
        if not protocol:
            return (False, PROPERTY_MISSING % {'p':key})
        if protocol not in valid_protocols:
            return (False, PROPERTY_INVALID % {'p':key, 'v':valid_protocols})
        for key in ('http', 'https'):
            section = config.get(key)
            if not section:
                return (False, PROPERTY_MISSING % {'p':key})
            key = (key, 'alias')
            alias = section.get(key[1])
            if not alias:
                return (False, PROPERTY_MISSING % {'p':'.'.join(key)})
        return (True, None)

    def publish_repo(self, repo, conduit, config):
        """
        Publishes the given repository.
        While this call may be implemented using multiple threads, its execution
        from the Pulp server's standpoint should be synchronous. This call should
        not return until the publish is complete.

        It is not expected that this call be atomic. Should an error occur, it
        is not the responsibility of the distributor to rollback any changes
        that have been made.

        :param repo: metadata describing the repository
        :type  repo: pulp.plugins.model.Repository
        :param conduit: provides access to relevant Pulp functionality
        :type  conduit: pulp.plugins.conduits.repo_publish.RepoPublishConduit
        :param config: plugin configuration
        :type  config: pulp.plugins.config.PluginConfiguration
        :return: report describing the publish run
        :rtype:  pulp.plugins.model.PublishReport
        """
        nodes_conduit = NodesConduit()
        units = nodes_conduit.get_units(repo.id)
        with self.publisher(repo, config) as publisher:
            manifest_path = publisher.publish(units)
            manifest = Manifest()
            manifest.read(manifest_path)
            publisher.commit()
        details = dict(unit_count=len(units))
        scratchpad = {constants.MANIFEST_ID_SCRATCHPAD_KEY: manifest.id}
        conduit.update_repo_scratchpad(scratchpad)
        return conduit.build_success_report('succeeded', details)

    def publisher(self, repo, config):
        """
        Get a configured publisher.
        :param repo: A repository.
        :type repo: pulp.plugins.model.Repository
        :param config: plugin configuration
        :type  config: pulp.plugins.config.PluginConfiguration
        :return: The configured publisher.
        """
        protocol = config.get(constants.PROTOCOL_KEYWORD)
        host = pulp_conf.get('server', 'server_name')
        section = config.get(protocol)
        alias = section.get('alias')
        base_url = '://'.join((protocol, host))
        return HttpPublisher(base_url, alias, repo.id)

    def cancel_publish_repo(self, call_report, call_request):
        pass

    def create_consumer_payload(self, repo, config, binding_config):
        """
        Called when a consumer binds to a repository using this distributor.
        This call should return a dictionary describing all data the consumer
        will need to access the repository. The contents will vary wildly
        depending on the method the repository is published, but examples
        of returned data includes authentication information, location of the
        repository (e.g. URL), and data required to verify the contents
        of the published repository.
        :param repo: metadata describing the repository
        :type  repo: pulp.plugins.model.Repository
        :param config: plugin configuration
        :type  config: pulp.plugins.config.PluginCallConfiguration
        :param binding_config: The configuration stored on the binding.
        :type binding_config: dict
        :return: dictionary of relevant data
        :rtype:  dict
        """
        payload = {}
        self._add_repository(repo.id, payload)
        self._add_importers(repo, config, binding_config or {}, payload)
        self._add_distributors(repo.id, payload)
        return payload

    def _add_repository(self, repo_id, payload):
        """
        Add repository information to the payload.
        :param repo_id: The repository ID.
        :type repo_id: str
        :param payload: The repository payload
        :type payload: dict
        """
        manager = factory.repo_query_manager()
        payload['repository'] = manager.get_repository(repo_id)

    def _add_importers(self, repo, config, binding_config, payload):
        """
        Add the nodes importer.
        :param repo: A repo object.
        :type repo: pulp.plugins.model.Repository
        :param config: plugin configuration
        :type  config: pulp.plugins.config.PluginCallConfiguration
        :param binding_config: The configuration stored on the binding.
        :type binding_config: dict
        :param payload: The bind payload.
        :type payload: dict
        """
        conf = self._importer_conf(repo, config, binding_config)
        importer = {
            'id': constants.HTTP_IMPORTER,
            'importer_type_id': constants.HTTP_IMPORTER,
            'config': conf,
        }
        payload['importers'] = [importer]

    def _importer_conf(self, repo, config, binding_config):
        """
        Build the nodes importer configuration.
        :param repo: A repo object.
        :type repo: pulp.plugins.model.Repository
        :param config: plugin configuration
        :type  config: pulp.plugins.config.PluginCallConfiguration
        :param binding_config: The configuration stored on the binding.
        :type binding_config: dict
        :return: The importer configuration.
        :rtype: dict
        """
        publisher = self.publisher(repo, config)
        protocol = config.get(constants.PROTOCOL_KEYWORD)
        manifest_url = '/'.join((publisher.base_url, publisher.manifest_path()))
        protocol_section = config.get(protocol)
        ssl_dict = protocol_section.get('ssl', {})
        ssl_conf = self._ssl_conf(ssl_dict)
        strategy = binding_config.get(constants.STRATEGY_KEYWORD, constants.DEFAULT_STRATEGY)
        conf = {
            constants.STRATEGY_KEYWORD: strategy,
            constants.MANIFEST_URL_KEYWORD: manifest_url,
            constants.PROTOCOL_KEYWORD: protocol,
            constants.SSL_KEYWORD: ssl_conf,
        }
        return conf

    def _ssl_conf(self, ssl_dict):
        """
        Build the SSL configuration.
        The certificate paths are replaced with packed links.
        :param ssl_dict: The SSL part of the configuration.
        :type ssl_dict: dict
        :return: A built SSL configuration.
        :rtype: dict
        :see: Link
        """
        if not ssl_dict:
            return {}
        conf = {}
        for key in (constants.CLIENT_CERT_KEYWORD,):
            value = ssl_dict.get(key)
            path = value['local']
            path_out = value['child']
            conf[key] = link.pack(path, path_out)
        return conf

    def _add_distributors(self, repo_id, payload):
        """
        Add repository distributors information to the payload.
        :param repo_id: The repository ID.
        :type repo_id: str
        :param payload: The distributor(s) payload
        :type payload: dict
        """
        distributors = []
        manager = factory.repo_distributor_manager()
        for dist in manager.get_distributors(repo_id):
            if dist['distributor_type_id'] in constants.ALL_DISTRIBUTORS:
                continue
            distributors.append(dist)
        payload['distributors'] = distributors
