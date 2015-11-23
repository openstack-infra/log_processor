#!/usr/bin/python2
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import argparse
import daemon
import gear
import json
import logging
import os
import os.path
import re
import signal
import socket
import threading
import time
import yaml
import zmq


try:
    import daemon.pidlockfile as pidfile_mod
except ImportError:
    import daemon.pidfile as pidfile_mod


class EventProcessor(threading.Thread):
    def __init__(self, zmq_address, gearman_client, files, source_url):
        threading.Thread.__init__(self)
        self.files = files
        self.source_url = source_url
        self.gearman_client = gearman_client
        self.zmq_address = zmq_address
        self._connect_zmq()

    def run(self):
        while True:
            try:
                self._read_event()
            except:
                # Assume that an error reading data from zmq or deserializing
                # data received from zmq indicates a zmq error and reconnect.
                logging.exception("ZMQ exception.")
                self._connect_zmq()

    def _connect_zmq(self):
        logging.debug("Connecting to zmq endpoint.")
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        event_filter = b"onFinalized"
        self.socket.setsockopt(zmq.SUBSCRIBE, event_filter)
        self.socket.connect(self.zmq_address)

    def _get_event(self):
        return self.socket.recv().decode('utf-8')

    def _read_event(self):
        string = self._get_event()
        event = json.loads(string.split(None, 1)[1])
        logging.debug("Jenkins event received: " + json.dumps(event))
        for fileopts in self.files:
            output = {}
            source_url, out_event = self._parse_event(event, fileopts)
            job_filter = fileopts.get('job-filter')
            if (job_filter and
                not re.match(job_filter, out_event['fields']['build_name'])):
                continue
            build_queue_filter = fileopts.get('build-queue-filter')
            if (build_queue_filter and
                not re.match(build_queue_filter,
                             out_event['fields']['build_queue'])):
                continue
            project_filter = fileopts.get('project-filter')
            if (project_filter and
                not re.match(project_filter, out_event['fields']['project'])):
                continue
            output['source_url'] = source_url
            output['retry'] = fileopts.get('retry-get', False)
            output['event'] = out_event
            if 'subunit' in fileopts.get('name'):
                job = gear.Job(b'push-subunit',
                               json.dumps(output).encode('utf8'))
            else:
                job = gear.Job(b'push-log', json.dumps(output).encode('utf8'))
            try:
                self.gearman_client.submitJob(job)
            except:
                logging.exception("Exception submitting job to Gearman.")

    def _get_log_dir(self, event):
        parameters = event["build"].get("parameters", {})
        base = parameters.get('LOG_PATH', 'UNKNOWN')
        return base

    def _parse_fields(self, event, filename):
        fields = {}
        fields["filename"] = filename
        fields["build_name"] = event.get("name", "UNKNOWN")
        fields["build_status"] = event["build"].get("status", "UNKNOWN")
        fields["build_node"] = event["build"].get("node_name", "UNKNOWN")
        fields["build_master"] = event["build"].get("host_name", "UNKNOWN")
        parameters = event["build"].get("parameters", {})
        fields["project"] = parameters.get("ZUUL_PROJECT", "UNKNOWN")
        # The voting value is "1" for voting, "0" for non-voting
        fields["voting"] = parameters.get("ZUUL_VOTING", "UNKNOWN")
        # TODO(clarkb) can we do better without duplicated data here?
        fields["build_uuid"] = parameters.get("ZUUL_UUID", "UNKNOWN")
        fields["build_short_uuid"] = fields["build_uuid"][:7]
        fields["build_queue"] = parameters.get("ZUUL_PIPELINE", "UNKNOWN")
        fields["build_ref"] = parameters.get("ZUUL_REF", "UNKNOWN")
        fields["build_branch"] = parameters.get("ZUUL_BRANCH", "UNKNOWN")
        fields["build_zuul_url"] = parameters.get("ZUUL_URL", "UNKNOWN")
        if parameters.get("ZUUL_CHANGE"):
            fields["build_change"] = parameters.get("ZUUL_CHANGE", "UNKNOWN")
            fields["build_patchset"] = parameters.get("ZUUL_PATCHSET",
                                                      "UNKNOWN")
        elif parameters.get("ZUUL_NEWREV"):
            fields["build_newrev"] = parameters.get("ZUUL_NEWREV",
                                                    "UNKNOWN")
        if ["build_node"] != "UNKNOWN":
            node_region = '-'.join(
                fields["build_node"].split('-')[-3:-1])
            fields["node_region"] = node_region or "UNKNOWN"
        else:
            fields["node_region"] = "UNKNOWN"
        return fields

    def _parse_event(self, event, fileopts):
        fields = self._parse_fields(event, fileopts['name'])
        log_dir = self._get_log_dir(event)
        source_url = fileopts.get('source-url', self.source_url) + '/' + \
            os.path.join(log_dir, fileopts['name'])
        fields["log_url"] = source_url
        out_event = {}
        out_event["fields"] = fields
        out_event["tags"] = [os.path.basename(fileopts['name'])] + \
            fileopts.get('tags', [])
        return source_url, out_event


class Server(object):
    def __init__(self, config, debuglog):
        # Config init.
        self.config = config
        self.source_url = self.config['source-url']
        # Pythong logging output file.
        self.debuglog = debuglog
        self.processors = []

    def setup_logging(self):
        if self.debuglog:
            logging.basicConfig(format='%(asctime)s %(message)s',
                                filename=self.debuglog, level=logging.DEBUG)
        else:
            # Prevent leakage into the logstash log stream.
            logging.basicConfig(level=logging.CRITICAL)
        logging.debug("Log pusher starting.")

    def setup_processors(self):
        for publisher in self.config['zmq-publishers']:
            gearclient = gear.Client()
            gearclient.addServer('localhost')
            gearclient.waitForServer()
            log_processor = EventProcessor(
                publisher, gearclient,
                self.config['source-files'], self.source_url)
            subunit_processor = EventProcessor(
                publisher, gearclient,
                self.config['subunit-files'], self.source_url)
            self.processors.append(log_processor)
            self.processors.append(subunit_processor)

    def wait_for_name_resolution(self, host, port):
        while True:
            try:
                socket.getaddrinfo(host, port)
            except socket.gaierror as e:
                if e.errno == socket.EAI_AGAIN:
                    logging.debug("Temporary failure in name resolution")
                    time.sleep(2)
                    continue
                else:
                    raise
            break

    def main(self):
        statsd_host = os.environ.get('STATSD_HOST')
        statsd_port = int(os.environ.get('STATSD_PORT', 8125))
        statsd_prefix = os.environ.get('STATSD_PREFIX', 'logstash.geard')
        if statsd_host:
            self.wait_for_name_resolution(statsd_host, statsd_port)
        self.gearserver = gear.Server(
            statsd_host=statsd_host,
            statsd_port=statsd_port,
            statsd_prefix=statsd_prefix)

        self.setup_processors()
        for processor in self.processors:
            processor.daemon = True
            processor.start()
        while True:
            signal.pause()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True,
                        help="Path to yaml config file.")
    parser.add_argument("-d", "--debuglog",
                        help="Enable debug log. "
                             "Specifies file to write log to.")
    parser.add_argument("--foreground", action='store_true',
                        help="Run in the foreground.")
    parser.add_argument("-p", "--pidfile",
                        default="/var/run/jenkins-log-pusher/"
                                "jenkins-log-gearman-client.pid",
                        help="PID file to lock during daemonization.")
    args = parser.parse_args()

    with open(args.config, 'r') as config_stream:
        config = yaml.load(config_stream)
    server = Server(config, args.debuglog)

    if args.foreground:
        server.setup_logging()
        server.main()
    else:
        pidfile = pidfile_mod.TimeoutPIDLockFile(args.pidfile, 10)
        with daemon.DaemonContext(pidfile=pidfile):
            server.setup_logging()
            server.main()


if __name__ == '__main__':
    main()
