#!/usr/bin/python2
#
# Copyright 2015 Hewlett-Packard Enterprise Development, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
import os
import Queue
import testtools
import yaml

from log_processor import client, tests

class FakeEventProcessor(client.EventProcessor):
    def _connect_zmq(self):
        self.events = Queue.Queue()
        self.events.put(u'onFinalized {"name": "fake-job", "build": {}}')
        self.events.put(u'onFinalized {"name": "fake-job2", "build": {}}')

    def _get_event(self):
        return self.events.get(block=False)

class ClientTestCase(testtools.TestCase):
    def setUp(self):
        super(ClientTestCase, self).setUp()

        config_file = os.path.join(os.path.dirname(tests.__file__),
                                   'fixtures', 'client-config.yaml')
        with open(config_file, 'r') as config_stream:
            self.config = yaml.load(config_stream)

        zmq_publishers = self.config.get('zmq-publishers', [])
        gearman_client = mock.Mock()
        files = self.config.get('source-files', [])
        source_url = self.config.get('source-url', None)

        for zmq_publisher in zmq_publishers:
            self.log_processor = FakeEventProcessor(zmq_publisher,
                gearman_client, files, source_url)

    def test_client_get(self):
        event0 = self.log_processor._get_event()
        self.assertEqual(event0,
                u'onFinalized {"name": "fake-job", "build": {}}')

        event1 = self.log_processor._get_event()
        self.assertEqual(event1,
                u'onFinalized {"name": "fake-job2", "build": {}}')

    def test_client_read(self):
        self.log_processor._read_event()
        job_count = self.log_processor.gearman_client.submitJob.call_count
        self.assertEqual(job_count, 1)
