Log Processor
=============

Log Processor is a system for subscribing to a Jenkins ZMQ publisher
and acts as a Gearman server. When a Jenkins build finishes, Log Processor
Client will create Gearman jobs to fetch the build logs from a web server
and the Log Processor Workers will send those logs to a Logstash instance
running the tcp input plugin.

Contents:

.. toctree::
   :maxdepth: 2

   installation
   operation

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

