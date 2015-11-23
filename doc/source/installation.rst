:title: Installation

Installation
============

Log_processor consists of a client daemon and multiple worker daemons. The
client daemon subscribes to ZeroMQ on a Jenkins master listening for build
completes and then dispatches jobs to the worker daemons using gearman.

External Requirements
---------------------

Jenkins
~~~~~~~

You should have a Jenkins server running with the `ZMQ Event Publisher
<http://git.openstack.org/cgit/openstack-infra/zmq-event-publisher/tree/README>`_
plugin installed (it is available in the Jenkins Update Center).  Be
sure that the machine where you plan to run Log Processor can connect to
the ZMQ port specified by the plugin on your Jenkins master(s).

Logstash
~~~~~~~~

You should have Logstash running with the tcp input plugin. Be sure that
the machine where you plan to run Log Processor can connect to the tcp input
port specified in the logstash configuration.

Install Log Processor
---------------------

To install directly from git::

  git clone git://git.openstack.org/openstack-infra/log_processor.git /path/to/log_processor
  pip install /path/to/log_processor
