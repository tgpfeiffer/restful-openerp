#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

from lxml import etree

from twisted.web.http_headers import Headers
from twisted.internet.defer import Deferred, DeferredList

import feedvalidator
from feedvalidator import compatibility
from feedvalidator.formatter.text_plain import Formatter

from tests import OpenErpProxyTest, PrinterClient

class GetResponseCodesTest(OpenErpProxyTest):
  
  def test_whenNoBasicAuthThen401(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/',
        Headers({}),
        None)
    return d.addCallback(self._checkResponseCode, 401)

  def test_whenAccessToRootResourceThen405(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 405)

  ## test collection

  def test_whenWrongAuthToProperCollectionThen403(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)


  def test_whenAccessToProperCollectionThen200(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/product.product',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToProperCollectionWithGoodFilterThen200(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner?name=Test',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToProperCollectionWithBadFilterThen400(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner?xyz=Test',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToNonExistingCollectionThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partnerx',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  ## test resource

  def test_whenWrongAuthToProperResourceThen403(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToProperResourceThen200(self):
    # TODO: make sure that we actually have an existing resource
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToInvalidResourceThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToResourceChildThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToNonExistingResourceThen404(self):
    # TODO: make sure that we actually have an non-existing resource
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/-1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToAnotherNonExistingResourceThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/100000000',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  ## test schema

  def test_whenAccessToNonExistingSchemaThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partnerx/schema',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToProperSchemaThen200(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/schema',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenWrongAuthToProperSchemaThen403(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/schema',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  ## test defaults

  def test_whenAccessToProperDefaultsThen200(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/defaults',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 200)

  def test_whenAccessToNonExistingDefaultsThen404(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partnerx/defaults',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenWrongAuthToProperDefaultsThen403(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/defaults',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

class GetValidResponsesTest(OpenErpProxyTest):

  def _checkBody(self, response, callback):
    whenFinished = Deferred()
    response.deliverBody(PrinterClient(whenFinished))
    whenFinished.addCallback(callback)
    return whenFinished

  def _checkBodies(self, responses, callback, *params):
    deferreds = [Deferred() for r in responses]
    for i, (s, r) in enumerate(responses):
      r.deliverBody(PrinterClient(deferreds[i]))
    dl = DeferredList(deferreds)
    dl.addCallback(callback, *params)
    return dl

  def _isValidFeed(self, s):
    events = feedvalidator.validateString(s)['loggedEvents']
    fil = "A"
    filterFunc = getattr(compatibility, fil)
    events = filterFunc(events)
    output = Formatter(events)
    if output:
      print "\n".join(output)
    self.assertEqual(len(output), 0)

  def _isValidRelaxNg(self, s):
    doc = etree.fromstring(s)
    relaxng = etree.RelaxNG(doc)

  def _isValidXml(self, ((s1, schemaxml), (s2, docxml)), node):
    schema = etree.fromstring(schemaxml)
    relaxng = etree.RelaxNG(schema)
    doc = etree.fromstring(docxml).find("{http://www.w3.org/2005/Atom}content").find(node)
    valid = relaxng.validate(doc)
    if not valid:
      log = relaxng.error_log
      print log.last_error
    self.assertTrue(valid)

  def _isXmlButNotValid(self, ((s1, schemaxml), (s2, docxml)), node):
    schema = etree.fromstring(schemaxml)
    relaxng = etree.RelaxNG(schema)
    doc = etree.fromstring(docxml).find("{http://www.w3.org/2005/Atom}content").find(node)
    valid = relaxng.validate(doc)
    self.assertFalse(valid)

  ## test collection

  def test_whenAccessToProperCollectionThenValidFeed(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/product.product',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkBody, self._isValidFeed)

  ## test schema

  def test_whenAccessToProperSchemaThenValidRelaxNg(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/schema',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkBody, self._isValidRelaxNg)

  ## test item

  def test_whenAccessToProperResourceThenValidFeed(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkBody, self._isValidFeed)

  def test_whenAccessToProperResourceThenValidXml(self):
    d1 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/schema',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    d2 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    dl = DeferredList([d1, d2])
    return dl.addCallback(self._checkBodies, self._isValidXml, "{http://localhost:8068/" + self.db + "/res.partner/schema}res_partner")

  ## test defaults

  def test_whenAccessToProperDefaultsThenValidFeed(self):
    d = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/defaults',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkBody, self._isValidFeed)

  def test_whenAccessToProperDefaultsThenXmlButNotValid(self):
    d1 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/schema',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    d2 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/defaults',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    dl = DeferredList([d1, d2])
    return dl.addCallback(self._checkBodies, self._isXmlButNotValid, "{http://localhost:8068/" + self.db + "/res.partner/schema}res_partner")

  # to be tested:
  # * Last-Modified header exists and is well-formed in every response
  # * Last-Modified header for item corresponds to the <updated> field
