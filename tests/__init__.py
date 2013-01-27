#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser

from twisted.trial import unittest
from twisted.web.server import Site
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.web.client import Agent

from restfulOpenErpProxy import OpenErpDispatcher

# NB. to be run with 'trial' from the twisted test suite

class PrinterClient(Protocol):
  def __init__(self, whenFinished):
    self.whenFinished = whenFinished
    self.buffer = ""

  def dataReceived(self, bytes):
    self.buffer += bytes

  def connectionLost(self, reason):
    self.whenFinished.callback(self.buffer)

class OpenErpProxyTest(unittest.TestCase):

  def _checkResponseCode(self, response, code):
    self.assertEqual(response.code, code)
    return response

  def setUp(self):
    # read config
    config = ConfigParser.RawConfigParser()
    config.read(os.path.join(sys.path[0], 'restful-openerp.cfg'))
    openerpUrl = config.get("OpenERP", "url")
    self.user = config.get("Tests", "user")
    self.password = config.get("Tests", "password")
    self.basic = (self.user+":"+self.password).encode('base64')
    self.db = config.get("Tests", "db")
    # start listening
    self.root = OpenErpDispatcher(openerpUrl)
    self.factory = Site(self.root)
    self.server = reactor.listenTCP(8068, self.factory)
    self.client = None
    self.agent = Agent(reactor)

  def tearDown(self):
    for dbname, dbres in self.root.databases.iteritems():
      for modelname, modelres in dbres.models.iteritems():
        modelres.cleanUpTask.stop()
    if self.client is not None:
      self.client.transport.loseConnection()
    return self.server.stopListening()
