# Copyright (c) 2011 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from copy import deepcopy
import logging

import mock

from pulp.plugins.loader import api as plugin_api
from pulp.plugins.model import ApplicabilityReport
from pulp.server.compat import ObjectId
from pulp.server.db.model.consumer import (Consumer, Bind, RepoProfileApplicability,
                                           UnitProfile)
from pulp.server.db.model.dispatch import ScheduledCall
from pulp.server.db.model.repository import Repo, RepoDistributor
from pulp.server.dispatch import constants as dispatch_constants
from pulp.server.itineraries.bind import (
    bind_itinerary, unbind_itinerary, forced_unbind_itinerary)
from pulp.server.itineraries.consumer import (
    consumer_content_install_itinerary,
    consumer_content_update_itinerary,
    consumer_content_uninstall_itinerary)
from pulp.server.managers import factory
from pulp.server.managers.consumer.bind import BindManager
from pulp.server.managers.consumer.profile import ProfileManager
import base
import mock_plugins
import mock_agent


class ConsumerTest(base.PulpWebserviceTests):

    CONSUMER_ID = 'test-consumer'
    REPO_ID = 'test-repo'
    DISTRIBUTOR_ID = 'dist-1'
    NOTIFY_AGENT = True
    BINDING_CONFIG = {'b' : 'b'}
    DISTRIBUTOR_TYPE_ID = 'mock-distributor'

    def setUp(self):
        base.PulpWebserviceTests.setUp(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()

    def tearDown(self):
        base.PulpWebserviceTests.tearDown(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        mock_plugins.reset()

    def test_get(self):
        """
        Tests retrieving a valid consumer.
        """
        # Setup
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)
        path = '/v2/consumers/%s/' % self.CONSUMER_ID
        # Test
        status, body = self.get(path)
        # Verify
        self.assertEqual(200, status)
        self.assertEqual(self.CONSUMER_ID, body['id'])
        self.assertTrue('bindings' not in body)
        self.assertTrue('_href' in body)
        self.assertTrue(body['_href'].endswith(path))

    def test_get_with_bindings(self):
        """
        Test consumer with bindings.
        """
        # Setup
        manager = factory.repo_manager()
        manager.create_repo(self.REPO_ID)
        manager = factory.repo_distributor_manager()
        manager.add_distributor(
            self.REPO_ID,
            self.DISTRIBUTOR_TYPE_ID,
            {},
            True,
            distributor_id=self.DISTRIBUTOR_ID)
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        # Test
        params = {'bindings':True}
        path = '/v2/consumers/%s/' % self.CONSUMER_ID
        status, body = self.get(path, params=params)
        # Verify
        self.assertEqual(200, status)
        self.assertEqual(self.CONSUMER_ID, body['id'])
        self.assertTrue('_href' in body)
        self.assertTrue(body['_href'].endswith(path))
        self.assertTrue('bindings' in body)
        bindings = body['bindings']
        self.assertEquals(len(bindings), 1)
        self.assertEquals(bindings[0]['repo_id'], self.REPO_ID)
        self.assertEquals(bindings[0]['distributor_id'], self.DISTRIBUTOR_ID)
        self.assertEquals(bindings[0]['consumer_actions'], [])

    def test_get_with_details(self):
        """
        Test consumer with details.
        """
        # Setup
        manager = factory.repo_manager()
        manager.create_repo(self.REPO_ID)
        manager = factory.repo_distributor_manager()
        manager.add_distributor(
            self.REPO_ID,
            self.DISTRIBUTOR_TYPE_ID,
            {},
            True,
            distributor_id=self.DISTRIBUTOR_ID)
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        # Test
        params = {'details':True}
        path = '/v2/consumers/%s/' % self.CONSUMER_ID
        status, body = self.get(path, params=params)
        # Verify
        self.assertEqual(200, status)
        self.assertEqual(self.CONSUMER_ID, body['id'])
        self.assertTrue('_href' in body)
        self.assertTrue(body['_href'].endswith(path))
        self.assertTrue('bindings' in body)
        bindings = body['bindings']
        self.assertEquals(len(bindings), 1)
        self.assertEquals(bindings[0]['repo_id'], self.REPO_ID)
        self.assertEquals(bindings[0]['distributor_id'], self.DISTRIBUTOR_ID)
        self.assertEquals(bindings[0]['consumer_actions'], [])

    def test_get_missing_consumer(self):
        """
        Tests that a 404 is returned when getting a consumer that doesn't exist.
        """
        # Test
        status, body = self.get('/v2/consumers/foo/')
        # Verify
        self.assertEqual(404, status)

    def test_delete(self):
        """
        Tests unregistering an existing consumer.
        """
        # Setup
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)
        # Test
        path = '/v2/consumers/%s/' % self.CONSUMER_ID
        status, body = self.delete(path)
        # Verify
        self.assertEqual(200, status)

        consumer = Consumer.get_collection().find_one({'id' : 'doomed'})
        self.assertTrue(consumer is None)

    def test_delete_missing_consumer(self):
        """
        Tests deleting a consumer that isn't there.
        """
        # Test
        status, body = self.delete('/v2/consumers/fake/')
        # Verify
        self.assertEqual(404, status)

    def test_put(self):
        """
        Tests using put to update a consumer.
        """
        # Setup
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID, display_name='hungry')
        path = '/v2/consumers/%s/' % self.CONSUMER_ID
        body = {'delta' : {'display_name' : 'thanksgiving'}}
        # Test
        status, body = self.put(path, params=body)
        # Verify
        self.assertEqual(200, status)
        self.assertEqual(body['display_name'], 'thanksgiving')
        self.assertTrue(body['_href'].endswith(path))
        collection = Consumer.get_collection()
        consumer = collection.find_one({'id':self.CONSUMER_ID})
        self.assertEqual(consumer['display_name'], 'thanksgiving')

    def test_put_invalid_body(self):
        """
        Tests updating a consumer without passing the delta.
        """
        # Setup
        manager = factory.consumer_manager()
        manager.register('pie')
        # Test
        status, body = self.put('/v2/consumers/pie/', params={})
        # Verify
        self.assertEqual(400, status)

    def test_put_missing_consumer(self):
        """
        Tests updating a consumer that doesn't exist.
        """
        # Test
        body = {'delta' : {'pie' : 'apple'}}
        status, body = self.put('/v2/consumers/not-there/', params=body)
        # Verify
        self.assertEqual(404, status)


class ConsumersTest(base.PulpWebserviceTests):

    CONSUMER_IDS = ('test-consumer_1', 'test-consumer_2')
    REPO_ID = 'test-repo'
    DISTRIBUTOR_ID = 'dist-1'
    NOTIFY_AGENT = True
    BINDING_CONFIG = {'c' : 'c'}
    DISTRIBUTOR_TYPE_ID = 'mock-distributor'

    def setUp(self):
        base.PulpWebserviceTests.setUp(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()

    def tearDown(self):
        base.PulpWebserviceTests.tearDown(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        mock_plugins.reset()

    def populate(self, bindings=False):
        if bindings:
            manager = factory.repo_manager()
            manager.create_repo(self.REPO_ID)
            manager = factory.repo_distributor_manager()
            manager.add_distributor(
                self.REPO_ID,
                self.DISTRIBUTOR_TYPE_ID,
                {},
                True,
                distributor_id=self.DISTRIBUTOR_ID)
        for consumer_id in self.CONSUMER_IDS:
            manager = factory.consumer_manager()
            manager.register(consumer_id)
            if bindings:
                manager = factory.consumer_bind_manager()
                manager.bind(consumer_id, self.REPO_ID, self.DISTRIBUTOR_ID,
                             self.NOTIFY_AGENT, self.BINDING_CONFIG)

    def validate(self, body, bindings=False):
        if bindings:
            self.assertEqual(len(self.CONSUMER_IDS), len(body))
            fetched = dict([(c['id'],c) for c in body])
            for consumer_id in self.CONSUMER_IDS:
                consumer = fetched[consumer_id]
                self.assertEquals(consumer['id'], consumer_id)
                self.assertTrue('_href' in consumer)
                self.assertTrue('bindings' in consumer)
                bindings = consumer['bindings']
                self.assertEquals(len(bindings), 1)
                self.assertEquals(bindings[0]['consumer_id'], consumer_id)
                self.assertEquals(bindings[0]['repo_id'], self.REPO_ID)
                self.assertEquals(bindings[0]['distributor_id'], self.DISTRIBUTOR_ID)
                self.assertEquals(bindings[0]['deleted'], False)
                self.assertEquals(bindings[0]['consumer_actions'], [])

        else:
            self.assertEqual(len(self.CONSUMER_IDS), len(body))
            fetched = dict([(c['id'],c) for c in body])
            for consumer_id in self.CONSUMER_IDS:
                consumer = fetched[consumer_id]
                self.assertEquals(consumer['id'], consumer_id)
                self.assertTrue('_href' in consumer)
                self.assertFalse('bindings' in body)

    def test_get(self):
        """
        Tests retrieving a list of consumers.
        """
        # Setup
        self.populate()
        # Test
        status, body = self.get('/v2/consumers/')
        # Verify
        self.assertEqual(200, status)
        self.validate(body)

    def test_get_with_details(self):
        """
        Tests retrieving a list of consumers with details.
        """
        # Setup
        self.populate(True)
        # Test
        status, body = self.get('/v2/consumers/?details=1')
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)

    def test_get_with_bindings(self):
        """
        Tests retrieving a list of consumers with bindings.
        """
        # Setup
        self.populate(True)
        # Test
        status, body = self.get('/v2/consumers/?bindings=1')
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)

    def test_get_no_consumers(self):
        """
        Tests that an empty list is returned when no consumers are present.
        """
        # Test
        status, body = self.get('/v2/consumers/')
        # Verify
        self.assertEqual(200, status)
        self.assertEqual(0, len(body))

    def test_post(self):
        """
        Tests using post to register a consumer.
        """
        # Setup
        body = {
            'id' : self.CONSUMER_IDS[0],
            'display-name' : 'Consumer 1',
            'description' : 'Test Consumer',
        }
        # Test
        status, body = self.post('/v2/consumers/', params=body)
        # Verify
        self.assertEqual(201, status)
        self.assertEqual(body['id'], self.CONSUMER_IDS[0])
        collection = Consumer.get_collection()
        consumer = collection.find_one({'id' : self.CONSUMER_IDS[0]})
        self.assertTrue(consumer is not None)

    def test_post_bad_data(self):
        """
        Tests registering a consumer with invalid data.
        """
        # Setup
        body = {'id' : 'HA! This looks so totally invalid'}
        # Test
        status, body = self.post('/v2/consumers/', params=body)
        # Verify
        self.assertEqual(400, status)

    def test_post_conflict(self):
        """
        Tests creating a consumer with an existing ID.
        """
        # Setup
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_IDS[0])
        body = {'id' : self.CONSUMER_IDS[0]}
        # Test
        status, body = self.post('/v2/consumers/', params=body)
        # Verify
        self.assertEqual(409, status)


class TestSearch(ConsumersTest):

    FILTER = {'id':{'$in':ConsumersTest.CONSUMER_IDS}}
    SORT = [('id','ascending')]
    CRITERIA = dict(filters=FILTER, sort=SORT)

    def test_get(self):
        # Setup
        self.populate()
        # Test
        status, body = self.get('/v2/consumers/search/')
        # Verify
        self.assertEqual(200, status)
        self.validate(body)

    def test_get_with_details(self):
        # Setup
        self.populate(True)
        # Test
        status, body = self.get('/v2/consumers/search/?details=1')
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)

    def test_get_with_bindings(self):
        # Setup
        self.populate(True)
        # Test
        status, body = self.get('/v2/consumers/search/?bindings=1')
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)

    def test_post(self):
        # Setup
        self.populate()
        # Test
        body = {'criteria':self.CRITERIA}
        status, body = self.post('/v2/consumers/search/', body)
        # Verify
        self.validate(body)

    def test_post_with_details(self):
        # Setup
        self.populate(True)
        # Test
        body = {'criteria':self.CRITERIA, 'details':True}
        status, body = self.post('/v2/consumers/search/', body)
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)

    def test_post_with_bindings(self):
        # Setup
        self.populate(True)
        # Test
        body = {'criteria':self.CRITERIA, 'bindings':True}
        status, body = self.post('/v2/consumers/search/', body)
        # Verify
        self.assertEqual(200, status)
        self.validate(body, True)


class BindTest(base.PulpWebserviceTests):

    CONSUMER_ID = 'test-consumer'
    REPO_ID = 'test-repo'
    DISTRIBUTOR_ID = 'dist-1'
    NOTIFY_AGENT = True
    BINDING_CONFIG = {'a' : 'a'}
    DISTRIBUTOR_TYPE_ID = 'mock-distributor'
    QUERY = dict(
        consumer_id=CONSUMER_ID,
        repo_id=REPO_ID,
        distributor_id=DISTRIBUTOR_ID,
    )
    PAYLOAD = dict(
        server_name='pulp.redhat.com',
        relative_path='/repos/content/repoA',
        protocols=['https',],
        gpg_keys=['key1',],
        ca_cert='MY-CA',
        client_cert='MY-CLIENT-CERT')

    def setUp(self):
        base.PulpWebserviceTests.setUp(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()

    def tearDown(self):
        base.PulpWebserviceTests.tearDown(self)
        Consumer.get_collection().remove()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        Bind.get_collection().remove()
        mock_plugins.reset()

    def populate(self):
        manager = factory.repo_manager()
        manager.create_repo(self.REPO_ID)
        manager = factory.repo_distributor_manager()
        manager.add_distributor(
            self.REPO_ID,
            self.DISTRIBUTOR_TYPE_ID,
            {},
            True,
            distributor_id=self.DISTRIBUTOR_ID)
        mock_plugins.MOCK_DISTRIBUTOR.create_consumer_payload.return_value=self.PAYLOAD
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)

    def test_get_bind(self):
        # Setup
        self.populate()
        # Test
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        # Test
        path = '/v2/consumers/%s/bindings/%s/%s/' % \
            (self.CONSUMER_ID,
             self.REPO_ID,
             self.DISTRIBUTOR_ID)
        status, body = self.get(path)
        self.assertEquals(status, 200)
        self.assertTrue(body is not None)
        self.assertEquals(body['consumer_id'], self.CONSUMER_ID)
        self.assertEquals(body['repo_id'], self.REPO_ID)
        self.assertEquals(body['distributor_id'], self.DISTRIBUTOR_ID)
        self.assertTrue('_href' in body)

    def test_get_bind_by_consumer(self):
        # Setup
        self.populate()
        # Test
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        # Test
        path = '/v2/consumers/%s/bindings/' % self.CONSUMER_ID
        status, body = self.get(path)
        self.assertEquals(status, 200)
        self.assertEquals(len(body), 1)
        bind = body[0]
        self.assertEquals(bind['consumer_id'], self.CONSUMER_ID)
        self.assertEquals(bind['repo_id'], self.REPO_ID)
        self.assertEquals(bind['distributor_id'], self.DISTRIBUTOR_ID)
        self.assertTrue('_href' in bind)
        self.assertEquals(bind['details'], self.PAYLOAD)
        self.assertEquals(bind['type_id'], self.DISTRIBUTOR_TYPE_ID)

    def test_get_bind_by_consumer_and_repo(self):
        # Setup
        self.populate()
        # Test
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        # Test
        path = '/v2/consumers/%s/bindings/%s/' % (self.CONSUMER_ID, self.REPO_ID)
        status, body = self.get(path)
        self.assertEquals(status, 200)
        self.assertEquals(len(body), 1)
        bind = body[0]
        self.assertEquals(bind['consumer_id'], self.CONSUMER_ID)
        self.assertEquals(bind['repo_id'], self.REPO_ID)
        self.assertEquals(bind['distributor_id'], self.DISTRIBUTOR_ID)
        self.assertTrue('_href' in bind)
        self.assertEquals(bind['details'], self.PAYLOAD)
        self.assertEquals(bind['type_id'], self.DISTRIBUTOR_TYPE_ID)

    @mock.patch('pulp.server.webservices.controllers.consumers.bind_itinerary', wraps=bind_itinerary)
    def test_bind(self, mock_bind_itinerary):

        # Setup
        self.populate()

        # Test
        path = '/v2/consumers/%s/bindings/' % self.CONSUMER_ID
        body = dict(repo_id=self.REPO_ID, distributor_id=self.DISTRIBUTOR_ID,
                    notify_agent=self.NOTIFY_AGENT, binding_config=self.BINDING_CONFIG)
        status, body = self.post(path, body)

        # Verify
        self.assertEquals(status, 202)
        self.assertEqual(len(body), 2)
        for call in body:
            self.assertNotEqual(call['state'], dispatch_constants.CALL_REJECTED_RESPONSE)

        # verify itinerary called
        mock_bind_itinerary.assert_called_with(
                self.CONSUMER_ID,
                self.REPO_ID,
                self.DISTRIBUTOR_ID,
                self.NOTIFY_AGENT,
                self.BINDING_CONFIG,
                {})

    def test_bind_missing_consumer(self):
        # Setup
        self.populate()
        collection = Consumer.get_collection()
        collection.remove({})
        # Test
        path = '/v2/consumers/%s/bindings/' % self.CONSUMER_ID
        body = dict(
            repo_id=self.REPO_ID,
            distributor_id=self.DISTRIBUTOR_ID,)
        status, body = self.post(path, body)
        # Verify
        self.assertEquals(status, 404)
        manager = factory.consumer_bind_manager()
        binds = manager.find_by_consumer(self.CONSUMER_ID)
        self.assertEquals(len(binds), 0)

    def test_bind_missing_distributor(self):
        # Setup
        self.populate()
        collection = RepoDistributor.get_collection()
        collection.remove({})
        # Test
        path = '/v2/consumers/%s/bindings/' % self.CONSUMER_ID
        body = dict(
            repo_id=self.REPO_ID,
            distributor_id=self.DISTRIBUTOR_ID,)
        status, body = self.post(path, body)
        # Verify
        manager = factory.consumer_bind_manager()
        self.assertEquals(status, 404)
        binds = manager.find_by_consumer(self.CONSUMER_ID)
        self.assertEquals(len(binds), 0)

    @mock.patch('pulp.server.webservices.controllers.consumers.unbind_itinerary', wraps=unbind_itinerary)
    def test_unbind(self, mock_unbind_itinerary):

        # Setup
        self.populate()
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)

        # Test
        path = '/v2/consumers/%s/bindings/%s/%s/' % \
            (self.CONSUMER_ID,
             self.REPO_ID,
             self.DISTRIBUTOR_ID)
        status, body = self.delete(path)

        # Verify
        self.assertEquals(status, 202)
        self.assertEqual(len(body), 3)
        for call in body:
            self.assertNotEqual(call['state'], dispatch_constants.CALL_REJECTED_RESPONSE)

        # verify itinerary called
        mock_unbind_itinerary.assert_called_with(
            self.CONSUMER_ID,
            self.REPO_ID,
            self.DISTRIBUTOR_ID,
            {})

    @mock.patch('pulp.server.webservices.controllers.consumers.forced_unbind_itinerary', wraps=forced_unbind_itinerary)
    def test_forced_unbind(self, mock_unbind_itinerary):

        # Setup
        self.populate()
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)

        # Test
        path = '/v2/consumers/%s/bindings/%s/%s/' %\
               (self.CONSUMER_ID,
                self.REPO_ID,
                self.DISTRIBUTOR_ID)
        body = {'force':True}
        status, body = self.delete(path, body)

        # Verify
        self.assertEquals(status, 202)
        self.assertEqual(len(body), 2)
        for call in body:
            self.assertNotEqual(call['state'], dispatch_constants.CALL_REJECTED_RESPONSE)

        # verify itinerary called
        mock_unbind_itinerary.assert_called_with(
            self.CONSUMER_ID,
            self.REPO_ID,
            self.DISTRIBUTOR_ID,
            {})

    def test_unbind_missing_consumer(self):
        # Setup
        self.populate()
        collection = Consumer.get_collection()
        collection.remove({})
        # Test
        path = '/v2/consumers/%s/bindings/%s/%s/' %\
               (self.CONSUMER_ID,
                self.REPO_ID,
                self.DISTRIBUTOR_ID)
        status, body = self.delete(path)
        # Verify
        self.assertEquals(status, 404)
        manager = factory.consumer_bind_manager()
        binds = manager.find_by_consumer(self.CONSUMER_ID)
        self.assertEquals(len(binds), 0)

    def test_search(self):
        # Setup
        self.populate()
        manager = factory.consumer_bind_manager()
        manager.bind(self.CONSUMER_ID, self.REPO_ID, self.DISTRIBUTOR_ID,
                     self.NOTIFY_AGENT, self.BINDING_CONFIG)
        manager.action_pending(
            self.CONSUMER_ID,
            self.REPO_ID,
            self.DISTRIBUTOR_ID,
            Bind.Action.BIND,
            '0')

        # Test
        criteria = {'filters':
            {'consumer_actions.status':{'$in':['pending', 'failed']}}
        }
        path = '/v2/consumers/binding/search/'
        body = dict(criteria=criteria)
        status, body = self.post(path, body)

        # Verify
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)


class ContentTest(base.PulpWebserviceTests):

    CONSUMER_ID = 'test-consumer'

    @mock.patch('pulp.server.webservices.controllers.consumers.consumer_content_install_itinerary', wraps=consumer_content_install_itinerary)
    def test_install(self, mock_itinerary):
        # Test
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)
        path = '/v2/consumers/%s/actions/content/install/' % self.CONSUMER_ID
        body = dict(units=units, options=options)
        status, body = self.post(path, body)
        # Verify
        self.assertEquals(status, 202)
        mock_itinerary.assert_called_with(self.CONSUMER_ID, units, options)

    @mock.patch('pulp.server.webservices.controllers.consumers.consumer_content_update_itinerary', wraps=consumer_content_update_itinerary)
    def test_update(self, mock_itinerary):
        # Test
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)
        path = '/v2/consumers/%s/actions/content/update/' % self.CONSUMER_ID
        body = dict(units=units, options=options)
        status, body = self.post(path, body)
        # Verify
        self.assertEquals(status, 202)
        mock_itinerary.assert_called_with(self.CONSUMER_ID, units, options)

    @mock.patch('pulp.server.webservices.controllers.consumers.consumer_content_uninstall_itinerary', wraps=consumer_content_uninstall_itinerary)
    def test_uninstall(self, mock_itinerary):
        # Test
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)
        path = '/v2/consumers/%s/actions/content/uninstall/' % self.CONSUMER_ID
        body = dict(units=units, options=options)
        status, body = self.post(path, body)
        # Verify
        self.assertEquals(status, 202)
        mock_itinerary.assert_called_with(self.CONSUMER_ID, units, options)


class TestProfiles(base.PulpWebserviceTests):

    CONSUMER_ID = 'test-consumer'
    TYPE_1 = 'type-1'
    TYPE_2 = 'type-2'
    PROFILE_1 = {'name':'zsh', 'version':'1.0'}
    PROFILE_2 = {'name':'ksh', 'version':'2.0', 'arch':'x86_64'}

    def setUp(self):
        self.logger = logging.getLogger('pulp')
        base.PulpWebserviceTests.setUp(self)
        Consumer.get_collection().remove()
        UnitProfile.get_collection().remove()

    def tearDown(self):
        base.PulpWebserviceTests.tearDown(self)
        Consumer.get_collection().remove()
        UnitProfile.get_collection().remove()

    def populate(self):
        manager = factory.consumer_manager()
        manager.register(self.CONSUMER_ID)

    def sort(self, profiles):
        _sorted = []
        d = dict([(p['content_type'],p) for p in profiles])
        for k in sorted(d.keys()):
            _sorted.append(d[k])
        return _sorted

    def test_post(self):
        # Setup
        self.populate()
        # Test
        path = '/v2/consumers/%s/profiles/' % self.CONSUMER_ID
        body = dict(content_type=self.TYPE_1, profile=self.PROFILE_1)
        status, body = self.post(path, body)
        # Verify
        self.assertEqual(status, 201)
        self.assertEqual(body['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body['content_type'], self.TYPE_1)
        self.assertEqual(body['profile'], self.PROFILE_1)
        manager = factory.consumer_profile_manager()
        profile = manager.get_profile(self.CONSUMER_ID, self.TYPE_1)
        for key in ('consumer_id', 'content_type', 'profile'):
            self.assertEqual(body[key], profile[key])

    def test_put(self):
        # Setup
        self.populate()
        path = '/v2/consumers/%s/profiles/' % self.CONSUMER_ID
        body = dict(content_type=self.TYPE_1, profile=self.PROFILE_1)
        status, body = self.post(path, body)
        self.assertEqual(status, 201)
        self.assertEqual(body['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body['content_type'], self.TYPE_1)
        self.assertEqual(body['profile'], self.PROFILE_1)
        # Test
        path = '/v2/consumers/%s/profiles/%s/' % (self.CONSUMER_ID, self.TYPE_1)
        body = dict(profile=self.PROFILE_2)
        status, body = self.put(path, body)
        self.assertEqual(body['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body['content_type'], self.TYPE_1)
        self.assertEqual(body['profile'], self.PROFILE_2)
        manager = factory.consumer_profile_manager()
        profile = manager.get_profile(self.CONSUMER_ID, self.TYPE_1)
        for key in ('consumer_id', 'content_type', 'profile'):
            self.assertEqual(body[key], profile[key])
        self.assertEquals(profile['profile'], self.PROFILE_2)

    def test_delete(self):
        # Setup
        self.populate()
        manager = factory.consumer_profile_manager()
        manager.create(self.CONSUMER_ID, self.TYPE_1, self.PROFILE_1)
        manager.create(self.CONSUMER_ID, self.TYPE_2, self.PROFILE_2)
        profiles = manager.get_profiles(self.CONSUMER_ID)
        self.assertEquals(len(profiles), 2)
        # Test
        path = '/v2/consumers/%s/profiles/%s/' % (self.CONSUMER_ID, self.TYPE_1)
        status, body = self.delete(path)
        self.assertEqual(status, 200)
        profiles = manager.get_profiles(self.CONSUMER_ID)
        # Verify
        self.assertEquals(len(profiles), 1)
        profile = manager.get_profile(self.CONSUMER_ID, self.TYPE_2)
        self.assertTrue(profile is not None)

    def test_get_all(self):
        # Setup
        self.populate()
        manager = factory.consumer_profile_manager()
        manager.create(self.CONSUMER_ID, self.TYPE_1, self.PROFILE_1)
        manager.create(self.CONSUMER_ID, self.TYPE_2, self.PROFILE_2)
        # Test
        path = '/v2/consumers/%s/profiles/' % self.CONSUMER_ID
        status, body = self.get(path)
        # Verify
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 2)
        body = self.sort(body)
        self.assertEqual(body[0]['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body[0]['content_type'], self.TYPE_1)
        self.assertEqual(body[0]['profile'], self.PROFILE_1)
        self.assertEqual(body[1]['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body[1]['content_type'], self.TYPE_2)
        self.assertEqual(body[1]['profile'], self.PROFILE_2)

    def test_get_by_type(self):
        # Setup
        self.populate()
        manager = factory.consumer_profile_manager()
        manager.create(self.CONSUMER_ID, self.TYPE_1, self.PROFILE_1)
        manager.create(self.CONSUMER_ID, self.TYPE_2, self.PROFILE_2)
        # Test
        path = '/v2/consumers/%s/profiles/%s/' % (self.CONSUMER_ID, self.TYPE_1)
        status, body = self.get(path)
        self.assertEqual(status, 200)
        self.assertEqual(body['consumer_id'], self.CONSUMER_ID)
        self.assertEqual(body['content_type'], self.TYPE_1)
        self.assertEqual(body['profile'], self.PROFILE_1)

    def test_get_by_type_not_found(self):
        # Test
        path = '/v2/consumers/%s/profiles/unknown/' % self.CONSUMER_ID
        status, body = self.get(path)
        self.assertEqual(status, 404)

    def test_delete_not_found(self):
        # Test
        path = '/v2/consumers/%s/profiles/unknown/' % self.CONSUMER_ID
        status, body = self.delete(path)
        self.assertEqual(status, 404)


# We mock this because we don't care about consumer history in this test suite, and it
# saves some DB access time and cleanup
@mock.patch('pulp.server.managers.consumer.bind.factory.consumer_history_manager')
# By mocking this, we can avoid having to create repos and distributors for this test
# suite
@mock.patch('pulp.server.managers.consumer.bind.factory.repo_distributor_manager')
class TestContentApplicability(base.PulpWebserviceTests):
    """
    Test the ContentApplicability controller.
    """
    PATH = '/v2/consumers/actions/content/applicability/'

    def assert_applicability_matches(self, a_1, a_2):
        """
        This method will assert that the returned applicability data from the POST() method
        is the same as an expected_body passed to it. Order of lists doesn't matter for
        applicability, so this method transforms the data into sets first for comparison.

        :param a_1: The first applicability that you wish to test for equality with
        :type  a_1: list
        :param a_2: The second applicability that you wish to test for equality with
        :type  a_2: list
        """
        def _convert_to_set(a):
            """
            Traverse the given object, a, and turn all lists and dictionaries found in the
            structure into fronzensets.

            :param a: A structure to traverse, converting lists and dictionaries into
                      frozensets
            :type  a: object
            :return:  A representation of a that has frozensets in place of lists and dicts
            :rtype:   object
            """
            if isinstance(a, (list, tuple)):
                a = list(deepcopy(a))
                for index, item in enumerate(a):
                    a[index] = _convert_to_set(item)
                a = frozenset(a)
            elif isinstance(a, dict):
                a = deepcopy(a)
                for key, value in a.items():
                    a[key] = _convert_to_set(value)
                a = frozenset(a.items())
            return a
        self.assertEqual(_convert_to_set(a_1), _convert_to_set(a_2))

    def tearDown(self):
        """
        Empty the collections that were written to during this test suite.
        """
        super(TestContentApplicability, self).tearDown()
        Consumer.get_collection().remove()
        UnitProfile.get_collection().remove()
        RepoProfileApplicability.get_collection().drop()
        Bind.get_collection().drop()

    def test_POST_empty_type_limiting(self, consumer_history_manager,
                                      repo_distributor_manager):
        """
        Test the POST() method with an empty list as the type limiting criteria.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1', 'profile': ['unit_4-1.9']},
                           {'type': 'content_type_2',
                            'profile': ['unit_1-0.9.1', 'unit_2-1.1.3',
                                        'unit_3-12.0.13']}],
            'consumer_2': [{'type': 'content_type_2',
                            'profile': ['unit_1-0.8.7', 'unit_2-1.1.3',
                                        'unit_3-12.0.13']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_profile.content_type] = \
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile}
        # Create our precalcaulated applicability objects
        applicabilities = [
            {'profile_hash': profile_map['content_type_1']['hash'],
             'profile': profile_map['content_type_1']['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_4-1.9.1']}},
            {'profile_hash': profile_map['content_type_2']['hash'],
             'profile': profile_map['content_type_2']['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_1': ['unit_4-1.9.3'],
                               'content_type_2': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            {'profile_hash': profile_map['content_type_2']['hash'],
             'profile': profile_map['content_type_2']['profile'],
             'repo_id': 'repo_3',
             'applicability': {'content_type_2': ['unit_3-13.1.0']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        # Consumer 1 is bound to repo 1 and 2
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_1', 'repo_2', 'distributor_id', False, {})
        # Consumer 2 is bound to repo 2 and 3 (so it should get an additional unit_3)
        bind_manager.bind('consumer_2', 'repo_2', 'distributor_id', False, {})
        bind_manager.bind('consumer_2', 'repo_3', 'distributor_id', False, {})
        # The content_types below is the empty list, so nothing should come back
        criteria = {
            'consumer_criteria': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}},
            'content_types': []}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        # We told it not to give us any content types, so it should be empty
        self.assertEqual(body, [])

    def test_POST_invalid_consumer_criteria(self, consumer_history_manager,
                                            repo_distributor_manager):
        """
        Test the POST() method with invalid consumer criteria. HTTP 400 BAD REQUEST should be
        raised in each case.
        """
        # Test bad filters
        criteria = {
            'consumer_criteria': {
                'filters': 7}}
        status, body = self.post(self.PATH, criteria)
        self.assertEqual(status, 400)
        self.assertEqual(body, "Invalid properties: ['filters']")

    def test_POST_invalid_type_limiting(self, consumer_history_manager,
                                        repo_distributor_manager):
        """
        Test the POST() method with invalid type limiting criteria.
        """
        # Test with something that's not a list
        criteria = {
            'consumer_criteria': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}},
            'content_types': 42}
        status, body = self.post(self.PATH, criteria)
        self.assertEqual(status, 400)
        self.assertEqual(body, 'Invalid properties: [\'content_types must index a list.\']')

    def test_POST_limit_by_type(self, consumer_history_manager, repo_distributor_manager):
        """
        Test the POST() method, making sure we allow the caller to limit applicability
        data by unit type.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1', 'profile': ['unit_4-1.9']},
                           {'type': 'content_type_2',
                            'profile': ['unit_1-0.9.1', 'unit_2-1.1.3',
                                        'unit_3-12.0.13']}],
            'consumer_2': [{'type': 'content_type_2',
                            'profile': ['unit_1-0.9.1', 'unit_2-1.1.3',
                                        'unit_3-12.0.13']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_profile.content_type] = \
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile}
        # Create our precalcaulated applicability objects
        applicabilities = [
            # This one should not appear in the output since content_type_1 is excluded
            {'profile_hash': profile_map['content_type_1']['hash'],
             'profile': profile_map['content_type_1']['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_4-1.9.1']}},
            # The content_type_2 applicability data should be included in the output for
            # consumer_1 and consumer_2
            {'profile_hash': profile_map['content_type_2']['hash'],
             'profile': profile_map['content_type_2']['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_1': ['unit_4-1.9.3'],
                               'content_type_2': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            # Only consumer_2 is bound to repo_3, so this unit_3 should apply to only it
            {'profile_hash': profile_map['content_type_2']['hash'],
             'profile': profile_map['content_type_2']['profile'],
             'repo_id': 'repo_3',
             'applicability': {'content_type_2': ['unit_3-13.1.0']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        # Consumer 1 is bound to repo 1 and 2
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_1', 'repo_2', 'distributor_id', False, {})
        # Consumer 2 is bound to repo 2 and 3 (so it should get an additional unit_3)
        bind_manager.bind('consumer_2', 'repo_2', 'distributor_id', False, {})
        bind_manager.bind('consumer_2', 'repo_3', 'distributor_id', False, {})
        criteria = {
            'consumer_criteria': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}},
            'content_types': ['content_type_2']}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_1', 'consumer_2'],
             'applicability': {'content_type_2': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            {'consumers': ['consumer_2'],
             'applicability': {
                 'content_type_2': ['unit_3-13.1.0']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_match_consumers_with_same_applicability(self, consumer_history_manager,
                                                          repo_distributor_manager):
        """
        Test the POST() method, making sure we can handle consumers that share
        applicability correctly.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # In order for the consumers to have the same applicability, they will need the
        # same profile, so we'll just make one
        consumer_profile_data = ['unit_1-0.9.1', 'unit_2-1.1.3', 'unit_3-12.0.13']
        manager = ProfileManager()
        for consumer_id in consumer_ids:
            consumer_profile = manager.create(consumer_id, 'content_type',
                                              consumer_profile_data)
        # Create our precalcaulated applicability object
        applicability = {'content_type': ['unit_1-0.9.2', 'unit_3-13.0.1']}
        RepoProfileApplicability.objects.create(consumer_profile.profile_hash, 'repo_id',
                                                consumer_profile_data, applicability)
        # Create repository bindings to put them on the same repos
        bind_manager = BindManager()
        for consumer_id in consumer_ids:
            bind_manager.bind(consumer_id, 'repo_id', 'distributor_id', False, {})
        criteria = {
            'consumer_criteria': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}}}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_1', 'consumer_2'],
             'applicability': {'content_type': ['unit_1-0.9.2', 'unit_3-13.0.1']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_match_disparate_consumers(self, consumer_history_manager,
                                            repo_distributor_manager):
        """
        Test that the POST() method handles matching two consumers with different
        applicability data correctly.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1', 'profile': ['unit_4-1.9']}],
            'consumer_2': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_2-1.1.3',
                                        'unit_3-12.0.13']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            profile_map[consumer_id] = []
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_id].append(
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile})
        # Create our precalcaulated applicability objects
        applicabilities = [
            # Consumer_2's applicability
            {'profile_hash': profile_map['consumer_2'][0]['hash'],
             'profile': profile_map['consumer_2'][0]['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_1': ['unit_3-13.1.0']}},
            # Consumer_1's applicability
            {'profile_hash': profile_map['consumer_1'][0]['hash'],
             'profile': profile_map['consumer_1'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_2', 'repo_2', 'distributor_id', False, {})
        criteria = {
            'consumer_criteria': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}}}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_1'],
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            {'consumers': ['consumer_2'],
             'applicability': {'content_type_1': ['unit_3-13.1.0']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_match_mixed_case(self, consumer_history_manager, repo_distributor_manager):
        """
        Make sure the POST() method can handle a mixed case of consumers.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2', 'consumer_3']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_3-12.9.3']}],
            'consumer_2': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_3-12.9.3']},
                           {'type': 'content_type_2',
                            'profile': ['unit_3-12.9.0']}],
            'consumer_3': [{'type': 'content_type_1',
                            'profile': ['unit_2-2.0.13']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            profile_map[consumer_id] = []
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_id].append(
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile})
        # Create our precalcaulated applicability objects
        applicabilities = [
            # consumer_1 and 2's applicability
            {'profile_hash': profile_map['consumer_1'][0]['hash'],
             'profile': profile_map['consumer_1'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            # Consumer_2's applicability
            {'profile_hash': profile_map['consumer_2'][1]['hash'],
             'profile': profile_map['consumer_2'][1]['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_2': ['unit_3-13.1.0']}},
            # Consumer_3's applicability
            {'profile_hash': profile_map['consumer_3'][0]['hash'],
             'profile': profile_map['consumer_3'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_2-3.1.1']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        # Consumer_2 is bound to repo_1 and repo_2. It's binding to repo_2 gets it another
        # applicability
        bind_manager.bind('consumer_2', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_2', 'repo_2', 'distributor_id', False, {})
        bind_manager.bind('consumer_3', 'repo_1', 'distributor_id', False, {})
        # Match all consumers
        criteria = {'consumer_criteria': {'filters': {}}}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_1', 'consumer_2'],
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            {'consumers': ['consumer_2'],
             'applicability': {'content_type_2': ['unit_3-13.1.0']}},
            {'consumers': ['consumer_3'],
             'applicability': {'content_type_1': ['unit_2-3.1.1']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_match_single_consumer(self, consumer_history_manager,
                                        repo_distributor_manager):
        """
        Test that the POST() method handles matching a single consumer correctly.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1', 'consumer_2', 'consumer_3']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_3-12.9.3']}],
            'consumer_2': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_3-12.9.3']},
                           {'type': 'content_type_2',
                            'profile': ['unit_3-12.9.0']}],
            'consumer_3': [{'type': 'content_type_1',
                            'profile': ['unit_2-2.0.13']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            profile_map[consumer_id] = []
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_id].append(
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile})
        # Create our precalcaulated applicability objects
        applicabilities = [
            # consumer_1 and 2's applicability
            {'profile_hash': profile_map['consumer_1'][0]['hash'],
             'profile': profile_map['consumer_1'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            # Consumer_2's applicability
            {'profile_hash': profile_map['consumer_2'][1]['hash'],
             'profile': profile_map['consumer_2'][1]['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_2': ['unit_3-13.1.0']}},
            # Consumer_3's applicability
            {'profile_hash': profile_map['consumer_3'][0]['hash'],
             'profile': profile_map['consumer_3'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_2-3.1.1']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        # Consumer_2 is bound to repo_1 and repo_2. It's binding to repo_2 gets it another
        # applicability
        bind_manager.bind('consumer_2', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_2', 'repo_2', 'distributor_id', False, {})
        bind_manager.bind('consumer_3', 'repo_1', 'distributor_id', False, {})
        # Match consumer_2
        criteria = {'consumer_criteria': {'filters': {'id': 'consumer_2'}}}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_2'],
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1'],
                               'content_type_2': ['unit_3-13.1.0']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_multiple_applicability_data_matches(self, consumer_history_manager,
                                                      repo_distributor_manager):
        """
        Test that the POST() method properly handles the case when multiple
        applicability objects map to a consumer. They should get aggregated and not
        clobber each other.
        """
        # Set up the consumers
        consumer_ids = ['consumer_1']
        manager = factory.consumer_manager()
        for consumer_id in consumer_ids:
            manager.register(consumer_id)
        # Set up consumer profile data
        consumer_profiles = {
            'consumer_1': [{'type': 'content_type_1',
                            'profile': ['unit_1-0.9.1', 'unit_3-12.9.3']}]}
        manager = ProfileManager()
        profile_map = {}
        for consumer_id, profiles in consumer_profiles.items():
            profile_map[consumer_id] = []
            for profile in profiles:
                consumer_profile = manager.create(consumer_id, profile['type'],
                                                  profile['profile'])
                profile_map[consumer_id].append(
                    {'hash': consumer_profile.profile_hash,
                     'profile': consumer_profile.profile})
        # Create our precalcaulated applicability objects
        applicabilities = [
            # consumer_1's applicability from repo_1
            {'profile_hash': profile_map['consumer_1'][0]['hash'],
             'profile': profile_map['consumer_1'][0]['profile'],
             'repo_id': 'repo_1',
             'applicability': {'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1']}},
            # Consumer_1's applicability from repo_2
            {'profile_hash': profile_map['consumer_1'][0]['hash'],
             'profile': profile_map['consumer_1'][0]['profile'],
             'repo_id': 'repo_2',
             'applicability': {'content_type_1': ['unit_3-13.1.0']}}]
        for a in applicabilities:
            RepoProfileApplicability.objects.create(a['profile_hash'], a['repo_id'],
                                                    a['profile'], a['applicability'])
        # Create repository bindings
        bind_manager = BindManager()
        bind_manager.bind('consumer_1', 'repo_1', 'distributor_id', False, {})
        bind_manager.bind('consumer_1', 'repo_2', 'distributor_id', False, {})
        criteria = {'consumer_criteria': {'filters': {}}}

        status, body = self.post(self.PATH, criteria)

        # We should get the criteria for the single consumer back
        self.assertEqual(status, 200)
        expected_body = [
            {'consumers': ['consumer_1'],
             'applicability': {
                 'content_type_1': ['unit_1-0.9.2', 'unit_3-13.0.1', 'unit_3-13.1.0']}}]
        self.assert_applicability_matches(body, expected_body)

    def test_POST_no_consumer_criteria(self, consumer_history_manager,
                                       repo_distributor_manager):
        """
        Test the POST() method when no consumer criteria is passed.
        """
        # Test no criteria
        status, body = self.post(self.PATH, '')
        self.assertEqual(status, 400)
        self.assertEqual(body, 'Invalid properties: ["The input to this method must be a '
                               'JSON document with a \'consumer_criteria\' key."]')

        # Test wrong consumer_criteria key
        criteria = {
            'wrong_key': {
                'filters': {'id': {'$in': ['consumer_1', 'consumer_2']}}}}
        status, body = self.post(self.PATH, criteria)
        self.assertEqual(status, 400)
        self.assertEqual(body, 'Invalid properties: [\'criteria\']')

    def test_POST_non_matching_consumer_criteria(self):
        """
        Test the POST() method when the given consumer criteria does not match any
        consumers.
        """
        criteria = {'consumer_criteria': {'filters': {'_id': 'does_not_exist'}}}

        status, body = self.post(self.PATH, criteria)

        self.assertEqual(status, 200)
        # The body should be an empty dictionary, since no consumers matched
        self.assertEqual(body, {})

    def test_unmatched_applicability_data(self, consumer_history_manager,
                                          repo_distributor_manager):
        """
        Assert that applicability data that doesn't match any queried consumers is not
        returned.
        """
        self.fail()

    def test__add_consumers_to_applicability_map(self):
        """
        Test the _add_consumers_to_applicability_map() method.
        """
        self.fail()

    def test__add_profiles_to_consumer_map_and_get_hashes(self):
        """
        Test the _add_profiles_to_consumer_map_and_get_hashes() method.
        """
        self.fail()

    def test__add_repo_ids_to_consumer_map(self):
        """
        Test the _add_repo_ids_to_consumer_map() method.
        """
        self.fail()

    def test__format_report(self, consumer_history_manager, repo_distributor_manager):
        """
        Test the _format_report() method.
        """
        self.fail()

    def test__format_report_removes_empty_applicabilities(self, consumer_history_manager,
                                                          repo_distributor_manager):
        """
        Assert that _format_report() doesn't report applicabilities that didn't match
        any queried consumers.
        """
        self.fail()

    def test__get_applicability_map(self):
        """
        Test the _get_applicability_map() method.
        """
        self.fail()

    def test__get_consumer_applicability_map(self):
        """
        Test the _get_consumer_applicability_map() method.
        """
        self.fail()

    def test__get_consumer_applicability_map_with_repeat_consumer_sets(self):
        """
        Test the _get_consumer_applicability_map() method when there is more than one
        entry in the applicability_map for the same set of consumers.
        """
        self.fail()

    def test__get_consumer_ids(self):
        """
        Test the _get_consumer_ids() method.
        """
        self.fail()


# scheduled content management tests -------------------------------------------

class ScheduledUnitInstallTests(base.PulpWebserviceTests):

    def setUp(self):
        super(ScheduledUnitInstallTests, self).setUp()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()
        self.consumer_id = 'test-consumer'
        self.consumer_manager = factory.consumer_manager()
        self.consumer_manager.register(self.consumer_id)

    def tearDown(self):
        super(ScheduledUnitInstallTests, self).tearDown()
        self.consumer_manager = None
        Consumer.get_collection().remove(safe=True)
        ScheduledCall.get_collection().remove(safe=True)
        mock_plugins.reset()

    def test_create_scheduled_install(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, body = self.post(path, body)
        self.assertEquals(status, 201)

    def test_create_scheduled_install_bad_consumer(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/invalid-consumer/schedules/content/install/'
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 404)

    def test_get_scheduled_install(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/install/%s/' % (self.consumer_id, response['_id'])

        status, response = self.get(path)

        self.assertEqual(status, 200)

    def test_get_all_scheduled_installs(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id

        status, response = self.get(path)

        self.assertEqual(status, 200)
        self.assertEqual(len(response), 1)

    def test_get_scheduled_install_bad_consumer(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/invalid-consumer/schedules/content/install/%s/' % schedule_id
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_scheduled_install_bad_schedule(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/%s/schedules/content/install/%s/' % (self.consumer_id, schedule_id)
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_all_scheduled_installs_bad_consumer(self):
        path = '/v2/consumers/invalid-consumer/schedules/content/install/'
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_update_scheduled_install(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/install/%s/' % (self.consumer_id, schedule_id)
        update_body = {'schedule': 'R2/PT1H'}

        status, response = self.put(update_path, update_body)
        self.assertEqual(status, 200)

    def test_delete_scheduled_install(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/install/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/install/%s/' % (self.consumer_id, schedule_id)

        status, response = self.delete(update_path)
        self.assertEqual(status, 200)



class ScheduledUnitUpdateTests(base.PulpWebserviceTests):

    def setUp(self):
        super(ScheduledUnitUpdateTests, self).setUp()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()
        self.consumer_id = 'test-consumer'
        self.consumer_manager = factory.consumer_manager()
        self.consumer_manager.register(self.consumer_id)

    def tearDown(self):
        super(ScheduledUnitUpdateTests, self).tearDown()
        self.consumer_manager = None
        Consumer.get_collection().remove(safe=True)
        ScheduledCall.get_collection().remove(safe=True)
        mock_plugins.reset()

    def test_create_scheduled_update(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, body = self.post(path, body)
        self.assertEquals(status, 201)

    def test_create_scheduled_update_bad_consumer(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/invalid-consumer/schedules/content/update/'
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 404)

    def test_get_scheduled_update(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/update/%s/' % (self.consumer_id, response['_id'])

        status, response = self.get(path)

        self.assertEqual(status, 200)

    def test_get_all_scheduled_updates(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id

        status, response = self.get(path)

        self.assertEqual(status, 200)
        self.assertEqual(len(response), 1)

    def test_get_scheduled_update_bad_consumer(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/invalid-consumer/schedules/content/update/%s/' % schedule_id
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_scheduled_update_bad_schedule(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/%s/schedules/content/update/%s/' % (self.consumer_id, schedule_id)
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_all_scheduled_updates_bad_consumer(self):
        path = '/v2/consumers/invalid-consumer/schedules/content/update/'
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_update_scheduled_update(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/update/%s/' % (self.consumer_id, schedule_id)
        update_body = {'schedule': 'R2/PT1H'}

        status, response = self.put(update_path, update_body)
        self.assertEqual(status, 200)

    def test_delete_scheduled_update(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/update/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/update/%s/' % (self.consumer_id, schedule_id)

        status, response = self.delete(update_path)
        self.assertEqual(status, 200)



class ScheduledUnitUninstallTests(base.PulpWebserviceTests):

    def setUp(self):
        super(ScheduledUnitUninstallTests, self).setUp()
        plugin_api._create_manager()
        mock_plugins.install()
        mock_agent.install()
        self.consumer_id = 'test-consumer'
        self.consumer_manager = factory.consumer_manager()
        self.consumer_manager.register(self.consumer_id)

    def tearDown(self):
        super(ScheduledUnitUninstallTests, self).tearDown()
        self.consumer_manager = None
        Consumer.get_collection().remove(safe=True)
        ScheduledCall.get_collection().remove(safe=True)
        mock_plugins.reset()

    def test_create_scheduled_uninstall(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, body = self.post(path, body)
        self.assertEquals(status, 201)

    def test_create_scheduled_uninstall_bad_consumer(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/invalid-consumer/schedules/content/uninstall/'
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 404)

    def test_get_scheduled_uninstall(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/uninstall/%s/' % (self.consumer_id, response['_id'])

        status, response = self.get(path)

        self.assertEqual(status, 200)

    def test_get_all_scheduled_uninstalls(self):
        schedule = 'R1/P1DT'
        zsh_unit = {'type_id': 'rpm',
                    'unit_key': {'name': 'zsh'}}
        options = {'importkeys': True}

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id
        body = {'schedule': schedule,
                'units': [zsh_unit],
                'options': options}

        status, response = self.post(path, body)

        self.assertEqual(status, 201)

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id

        status, response = self.get(path)

        self.assertEqual(status, 200)
        self.assertEqual(len(response), 1)

    def test_get_scheduled_uninstall_bad_consumer(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/invalid-consumer/schedules/content/uninstall/%s/' % schedule_id
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_scheduled_uninstall_bad_schedule(self):
        schedule_id = str(ObjectId())
        path = '/v2/consumers/%s/schedules/content/uninstall/%s/' % (self.consumer_id, schedule_id)
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_get_all_scheduled_uninstalls_bad_consumer(self):
        path = '/v2/consumers/invalid-consumer/schedules/content/uninstall/'
        status, response = self.get(path)
        self.assertEqual(status, 404)

    def test_update_scheduled_uninstall(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/uninstall/%s/' % (self.consumer_id, schedule_id)
        update_body = {'schedule': 'R2/PT1H'}

        status, response = self.put(update_path, update_body)
        self.assertEqual(status, 200)

    def test_delete_scheduled_uninstall(self):
        unit_key = dict(name='zsh')
        unit = dict(type_id='rpm', unit_key=unit_key)
        units = [unit,]
        options = dict(importkeys=True)

        path = '/v2/consumers/%s/schedules/content/uninstall/' % self.consumer_id
        body = {'schedule': 'R1/PT1H',
                'units': units,
                'options': options}

        status, response = self.post(path, body)
        self.assertEquals(status, 201)

        schedule_id = response['_id']
        update_path = '/v2/consumers/%s/schedules/content/uninstall/%s/' % (self.consumer_id, schedule_id)

        status, response = self.delete(update_path)
        self.assertEqual(status, 200)
