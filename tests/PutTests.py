#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2013 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

from lxml import etree

from zope.interface import implements

from twisted.web.http_headers import Headers
from twisted.internet.defer import Deferred
from twisted.internet.defer import succeed
from twisted.web.iweb import IBodyProducer

from tests import OpenErpProxyTest, PrinterClient

class StringProducer(object):
  implements(IBodyProducer)

  def __init__(self, body):
    self.body = body
    self.length = len(body)

  def startProducing(self, consumer):
    consumer.write(self.body)
    return succeed(None)

  def pauseProducing(self):
    pass

  def stopProducing(self):
    pass

class PutResponseCodesTest(OpenErpProxyTest):

  def test_whenNoBasicAuthThen401(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/',
        Headers({}),
        None)
    return d.addCallback(self._checkResponseCode, 401)

  def test_whenAccessToRootResourceThen501(self):
    # Twisted gives 405 for POST but 501 for PUT???
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 501)

  ## test collection

  def test_whenWrongAuthToProperCollectionThen403(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToNonExistingCollectionThen404(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partnerx',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  ## test resource

  def test_whenWrongAuthToProperResourceThen403(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToInvalidResourceThen400(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToResourceChildThen400(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/4/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToNonExistingResourceThen404(self):
    # TODO: make sure that we actually have an non-existing resource
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/-1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  def test_whenAccessToAnotherNonExistingResourceThen404(self):
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/100000000',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  # NB. we do not have a simple test for "whenAccessToProperCollection" since
  #  this situation is much more difficult

class PutCorrectValidationsTest(OpenErpProxyTest):

  def _doSomethingWithBody(self, response, callback):
    whenFinished = Deferred()
    response.deliverBody(PrinterClient(whenFinished))
    whenFinished.addCallback(callback)
    return whenFinished

  def _checkResponse(self, response, code, value):
    self.assertEqual(response.code, code)
    # check for responseBody.startswith(value):
    return self._doSomethingWithBody(response, lambda x: self.assertEqual(x[:len(value)], value))

  def _checkResponseCode(self, response, code):
    self.assertEqual(response.code, code)
    return response

  def _checkResponseHeader(self, response, code, header, value):
    self.assertEqual(response.code, code)
    self.assertTrue(response.headers.hasHeader(header))
    self.assertEqual(response.headers.getRawHeaders(header)[0][:len(value)], value)

  def test_whenMalformedXmlThen400(self):
    xml = """<entry></content>"""
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        StringProducer(xml))
    return d.addCallback(self._checkResponse, 400, "malformed XML")

  def test_whenInvalidXmlThen400(self):
    xml = """<res_partner xmlns="http://localhost:8068/%s/res.partner/schema"></res_partner>""" % self.db
    d = self.agent.request(
        'PUT',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        StringProducer(xml))
    return d.addCallback(self._checkResponse, 400, "invalid XML:\n<string>:1:0:ERROR:RELAXNGV:RELAXNG_ERR_NOELEM: Expecting an element id, got nothing")

  def test_whenDefaultsThen400(self):
    def makeNextCall(xml):
      content = etree.tostring(etree.fromstring(xml).find("{http://www.w3.org/2005/Atom}content").find("{http://localhost:8068/" + self.db + "/res.partner/schema}res_partner"))
      d = self.agent.request(
          'PUT',
          'http://localhost:8068/' + self.db + '/res.partner/4',
          Headers({'Authorization': ['Basic %s' % self.basic]}),
          StringProducer(content))
      # will fail validation at mandatory, not-given fields
      return d.addCallback(self._checkResponse, 400, "invalid XML:\n<string>:48:0:ERROR:RELAXNGV:RELAXNG_ERR_DATATYPE: Error validating datatype string")

  def test_whenExistingWithNameThen204(self):
    def insertData(xml):
      doc = etree.fromstring(xml).find("{http://www.w3.org/2005/Atom}content").find("{http://localhost:8068/" + self.db + "/res.partner/schema}res_partner")
      doc.find("{http://localhost:8068/" + self.db + "/res.partner/schema}name").text = "Test Partner"
      content = etree.tostring(doc)
      d = self.agent.request(
          'PUT',
          'http://localhost:8068/' + self.db + '/res.partner/4',
          Headers({'Authorization': ['Basic %s' % self.basic]}),
          StringProducer(content))
      return d.addCallback(self._checkResponseCode, 204)

    d1 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d1.addCallback(self._doSomethingWithBody, insertData)

  def test_whenExistingWithSomeDataAndLookupThen200(self):
    def insertData(xml):
      doc = etree.fromstring(xml).find("{http://www.w3.org/2005/Atom}content").find("{http://localhost:8068/" + self.db + "/res.partner/schema}res_partner")
      doc.find("{http://localhost:8068/" + self.db + "/res.partner/schema}name").text = "Test Partner"
      doc.find("{http://localhost:8068/" + self.db + "/res.partner/schema}comment").text = "This is a test partner"
      content = etree.tostring(doc)
      d2 = self.agent.request(
          'PUT',
          'http://localhost:8068/' + self.db + '/res.partner/4',
          Headers({'Authorization': ['Basic %s' % self.basic]}),
          StringProducer(content))
      return d2.addCallback(lookupData)

    def __checkCorrectData(xml):
      answer = etree.fromstring(xml)
      self.assertEqual(answer.findtext(".//{http://localhost:8068/" + self.db + "/res.partner/schema}name"),
        "Test Partner")
      self.assertEqual(answer.findtext(".//{http://localhost:8068/" + self.db + "/res.partner/schema}comment"),
        "This is a test partner")

    def lookupData(response):
      d3 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
      d3.addCallback(self._checkResponseCode, 200)
      return d3.addCallback(self._doSomethingWithBody, lambda x: __checkCorrectData(x))

    d1 = self.agent.request(
        'GET',
        'http://localhost:8068/' + self.db + '/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d1.addCallback(self._doSomethingWithBody, insertData)
