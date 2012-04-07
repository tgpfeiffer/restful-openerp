#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser

from twisted.trial import unittest
from twisted.web.server import Site
from twisted.web.http_headers import Headers
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.defer import Deferred
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

  def setUp(self):
    # read config
    config = ConfigParser.RawConfigParser()
    config.read(os.path.join(sys.path[0], 'restful-openerp.cfg'))
    openerpUrl = config.get("OpenERP", "url")
    self.user = config.get("Tests", "user")
    self.password = config.get("Tests", "password")
    self.basic = (self.user+":"+self.password).encode('base64')
    # start listening
    root = OpenErpDispatcher(openerpUrl)
    self.factory = Site(root)
    self.server = reactor.listenTCP(8068, self.factory)
    self.client = None
    self.agent = Agent(reactor)

  def tearDown(self):
    if self.client is not None:
      self.client.transport.loseConnection()
    return self.server.stopListening()

  def _checkResponseCode(self, response, code):
    self.assertEqual(response.code, code)


class AuthenticationTest(OpenErpProxyTest):
  
  def test_ifNoBasicAuthThen401(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/',
        Headers({}),
        None)
    return d.addCallback(self._checkResponseCode, 401)

  def test_ifWrongAuthThen403(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToRootResourceThen405(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 405)

  def test_whenAccessToProperCollectionThen200(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToProperResourceThen200(self):
    # TODO: make sure that we actually have an existing resource
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToInvalidResourceThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToResourceChildThen404(self):
    # TODO: make sure that we actually have an existing resource
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner/4/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToNonExistingResourceThen404(self):
    # TODO: make sure that we actually have an non-existing resource
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner/-1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToAnotherNonExistingResourceThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/erptest/res.partner/100000000',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

